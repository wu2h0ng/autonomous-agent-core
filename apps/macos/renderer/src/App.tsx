import { useEffect, useMemo, useState } from "react";

import { createIdeShellState, currentSurface, destinationLabel, focusSurfaceWindow, type IdeShellState } from "./ide_shell";
import { resumeThread, type AgentThreadState } from "./panels/agent_thread";
import { decidePendingApproval, pendingApproval, type ApprovalDisposition } from "./panels/evidence_approval";
import { recentDiffs, type DiffSummary } from "./panels/diff";
import { fetchFiles, type FileEntry } from "./panels/files";
import { fetchOverview, type TaskOverview } from "./panels/plan_tasks";
import { terminalEvents, type TerminalLine } from "./panels/terminal";
import { SurfaceClient, type SessionSnapshot } from "./surface_client";
import { folderRequest, folderStatus, notifyApproval, runtimeConnection } from "./tauri";

type Phase = { kind: "connecting" } | { kind: "ready" } | { kind: "error"; message: string };
type PanelTab = "problems" | "output" | "terminal" | "ports";

const activities = [
  ["files", "▱", "资源管理器"], ["search", "⌕", "搜索"], ["git", "⑂", "源代码管理"],
  ["run", "▷", "运行与调试"], ["extensions", "◇", "扩展与技能"],
] as const;

function workspaceName(workspace: string | null): string {
  if (!workspace) return "选择工作区";
  return workspace.split("/").filter(Boolean).at(-1) ?? workspace;
}

function WindowBar({ shell, phase, onSwitch }: { shell: IdeShellState; phase: Phase; onSwitch: () => void }): React.JSX.Element {
  const status = phase.kind === "ready" ? "Runtime 已连接" : phase.kind === "connecting" ? "正在连接" : "Runtime 未连接";
  return <header className="window-bar">
    <div className="history-actions"><button aria-label="后退">‹</button><button aria-label="前进">›</button></div>
    <button className="command-center"><span>⌕</span>{workspaceName(shell.workspace)}</button>
    <div className="window-actions"><span className={`connection ${phase.kind}`}>{status}</span><button className="surface-link" onClick={onSwitch}>{destinationLabel(shell.surface)}</button><button aria-label="更多">•••</button></div>
  </header>;
}

function ActivityRail({ active, onChange }: { active: string; onChange: (id: string) => void }): React.JSX.Element {
  return <aside className="activity-rail" aria-label="IDE 工具"><div className="activity-stack">{activities.map(([id, icon, label]) => <button key={id} className={active === id ? "active" : ""} title={label} onClick={() => onChange(id)}><span>{icon}</span></button>)}</div><div className="activity-stack activity-bottom"><button title="账户">○</button><button title="设置">⚙</button></div></aside>;
}

function Explorer({ files, workspace, onOpenFolder }: { files: FileEntry[] | null; workspace: string | null; onOpenFolder: () => void }): React.JSX.Element {
  return <aside className="explorer">
    <div className="side-title"><span>资源管理器</span><button aria-label="更多">•••</button></div>
    {!workspace ? <div className="explorer-empty"><p>尚未打开文件夹</p><button className="accent-button" onClick={onOpenFolder}>打开文件夹</button></div> : <><div className="workspace-heading"><span>⌄</span><strong>{workspaceName(workspace).toUpperCase()}</strong></div><div className="file-tree">{files?.length ? files.slice(0, 30).map(file => <button key={file.path}><span>◇</span>{file.path}</button>) : <p className="empty-copy">当前工作尚未返回文件列表。</p>}</div></>}
    <div className="side-sections"><button>› 大纲</button><button>› 时间线</button></div>
  </aside>;
}

function WelcomeEditor({ onOpenFolder, onNewWork }: { onOpenFolder: () => void; onNewWork: () => void }): React.JSX.Element {
  return <section className="welcome-editor"><div className="welcome-mark">A</div><h1>Agent OS IDE</h1><p>选择代码环境，然后在同一个工作中浏览、修改、运行并审阅。</p><div className="welcome-actions"><button onClick={onOpenFolder}><span>▱</span><b>打开文件夹</b><small>选择本机或已授权的代码目录</small><kbd>⌘ O</kbd></button><button onClick={onNewWork}><span>＋</span><b>新建 Coding 工作</b><small>从目标开始建立代码工作</small><kbd>⌘ N</kbd></button></div><div className="shortcut-list"><div><span>打开命令面板</span><kbd>⇧ ⌘ P</kbd></div><div><span>快速打开文件</span><kbd>⌘ P</kbd></div><div><span>切换终端</span><kbd>⌃ `</kbd></div></div></section>;
}

function EditorCanvas({ files, workspace }: { files: FileEntry[] | null; workspace: string }): React.JSX.Element {
  const selected = files?.[0]?.path ?? "README.md";
  return <section className="editor-canvas"><div className="editor-tabs"><button className="active"><span>◇</span>{selected}<i>×</i></button></div><div className="breadcrumbs"><span>{workspaceName(workspace)}</span><b>›</b><span>{selected}</span></div><div className="editor-document"><div className="line-numbers">{Array.from({ length: 15 }, (_, i) => <span key={i}>{i + 1}</span>)}</div><div className="document-copy"><h1>{selected}</h1><p>文件内容读取能力尚未接入当前 Surface 协议。</p><p>资源管理器显示授权文件列表；内容读取、编辑缓冲区和语言服务将在对应协议接入后启用。</p></div></div></section>;
}

function BottomPanel({ tab, onTab, terminal, diffs }: { tab: PanelTab; onTab: (tab: PanelTab) => void; terminal: TerminalLine[] | null; diffs: DiffSummary[] | null }): React.JSX.Element {
  const tabs: [PanelTab, string][] = [["problems", "问题"], ["output", "输出"], ["terminal", "终端"], ["ports", "端口"]];
  return <section className="bottom-panel"><div className="panel-tabs">{tabs.map(([id, label]) => <button key={id} className={tab === id ? "active" : ""} onClick={() => onTab(id)}>{label}</button>)}<span /><button>＋</button><button>⌄</button></div><div className="panel-content">{tab === "terminal" ? terminal?.length ? terminal.map(line => <p key={line.sequence}>#{line.sequence} {line.summary}</p>) : <p><em>agent-os %</em> 等待运行命令</p> : tab === "problems" ? <p>{diffs?.length ?? 0} 个待审阅变更，0 个诊断问题</p> : <p>暂无{tab === "output" ? "输出" : "转发端口"}</p>}</div></section>;
}

function AgentPanel({ thread, snapshot, draft, notice, onDraft, onSend, onApprove, onReject }: { thread: AgentThreadState | null; snapshot: SessionSnapshot | null; draft: string; notice: string; onDraft: (value: string) => void; onSend: () => void; onApprove: () => void; onReject: () => void }): React.JSX.Element {
  return <aside className="agent-panel"><div className="agent-heading"><strong>Agent</strong><div><button title="新对话">＋</button><button title="历史">◷</button></div></div><div className="agent-thread">{thread?.messages.length ? thread.messages.map(message => <div className="thread-message" key={message.sequence}><small>#{message.sequence}</small><p>{message.kind}</p></div>) : <div className="agent-empty"><div className="agent-glyph">A</div><h2>与当前代码一起工作</h2><p>描述结果即可。系统按需使用技能和工具，不需要指定 Agent。</p></div>}{snapshot?.pending_approval ? <div className="approval-card"><small>需要决定</small><strong>{snapshot.pending_approval.capability_id}</strong><p>{snapshot.pending_approval.preview}</p><div><button onClick={onReject}>拒绝</button><button className="accent-button" onClick={onApprove}>允许</button></div></div> : null}{notice ? <p className="notice">{notice}</p> : null}</div><div className="agent-composer"><textarea value={draft} onChange={e => onDraft(e.target.value)} placeholder="规划与编程，@ 添加上下文，/ 使用技能" onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); onSend(); } }} /><div><button title="添加上下文">＋</button><span /><button title="语音">◉</button><button className="send-button" onClick={onSend}>↑</button></div></div></aside>;
}

function AgentSurface({ onOpenSession, snapshot, notice }: { onOpenSession: () => void; snapshot: SessionSnapshot | null; notice: string }): React.JSX.Element {
  return <main className="agent-surface"><section><div className="agent-logo">A</div><h1>把目标交给 Agent OS</h1><p>从一次提问，到可以持续推进的工作。</p><button className="accent-button" onClick={onOpenSession}>{snapshot ? "继续当前工作" : "新建工作"}</button>{notice ? <small>{notice}</small> : null}</section></main>;
}

export function App(): React.JSX.Element {
  const [phase, setPhase] = useState<Phase>({ kind: "connecting" });
  const [client, setClient] = useState<SurfaceClient | null>(null);
  const [snapshot, setSnapshot] = useState<SessionSnapshot | null>(null);
  const [thread, setThread] = useState<AgentThreadState | null>(null);
  const [files, setFiles] = useState<FileEntry[] | null>(null);
  const [overview, setOverview] = useState<TaskOverview | null>(null);
  const [diffs, setDiffs] = useState<DiffSummary[] | null>(null);
  const [terminal, setTerminal] = useState<TerminalLine[] | null>(null);
  const [draft, setDraft] = useState("");
  const [notice, setNotice] = useState("");
  const [shell, setShell] = useState<IdeShellState>(() => ({ ...createIdeShellState(), workspace: localStorage.getItem("agent-os.workspace") }));
  const [activity, setActivity] = useState("files");
  const [panelTab, setPanelTab] = useState<PanelTab>("terminal");

  useEffect(() => { void currentSurface().then(surface => setShell(current => ({ ...current, surface, ideView: surface === "ide" && current.workspace ? "editor" : current.ideView }))); }, []);

  async function switchWindow(): Promise<void> {
    const target = shell.surface === "agent" ? "ide" : "agent";
    try { await focusSurfaceWindow(target); } catch (error) { setNotice(`无法打开${target === "ide" ? "IDE" : "Agent"}窗口：${String(error)}`); }
  }

  useEffect(() => { let cancelled = false; void runtimeConnection().then(c => { if (!cancelled) { setClient(new SurfaceClient(c.base_url, c.bearer_token)); setPhase({ kind: "ready" }); } }).catch((error: unknown) => { if (!cancelled) { setPhase({ kind: "error", message: String(error) }); setNotice("桌面 Runtime 未连接；界面仍可预览，执行能力暂不可用。"); } }); return () => { cancelled = true; }; }, []);
  const statusCopy = useMemo(() => overview ? `${overview.task_status} · ${overview.run_status}` : "尚未开始工作", [overview]);

  async function openSession(): Promise<void> {
    if (!client) { setNotice("请先启动 Agent OS Runtime。"); return; }
    try { const opened = await client.openSession("interactive coding workspace"); setSnapshot(opened); const id = opened.session.task_id; setThread(await resumeThread(client, id, 0)); setFiles(await fetchFiles(client.baseUrlFor(), client.tokenFor(), id, fetch)); setOverview(await fetchOverview(client.baseUrlFor(), client.tokenFor(), id, fetch)); const events = await client.events(id, 0, 0); setDiffs(recentDiffs(events.events)); setTerminal(terminalEvents(events.events)); setNotice("Coding 工作已建立。"); } catch (error) { setNotice(`无法建立工作：${String(error)}`); }
  }
  async function requestWorkspace(): Promise<void> {
    try { await folderRequest(); const status = await folderStatus(); const path = status.granted ?? status.daemon_workspace; if (!path) { setNotice("尚未选择代码文件夹。"); return; } localStorage.setItem("agent-os.workspace", path); setShell(current => ({ ...current, workspace: path })); await focusSurfaceWindow("ide"); } catch (error) { setNotice(`无法打开文件夹：${String(error)}`); }
  }
  async function sendTurn(): Promise<void> {
    if (!client || !snapshot || !draft.trim()) return;
    try { const response = await client.runTurn(snapshot.session.session_id, draft); setSnapshot(response.snapshot); setDraft(""); if (response.snapshot.pending_approval) { setNotice(`需要确认：${response.snapshot.pending_approval.capability_id}`); void notifyApproval(response.snapshot.pending_approval.capability_id, response.snapshot.pending_approval.action_digest); } else setNotice(response.text || `[${response.stop_reason}]`); setThread(await resumeThread(client, snapshot.session.task_id, thread?.nextSequence ?? 0)); } catch (error) { setNotice(`执行失败：${String(error)}`); }
  }
  async function decideApproval(disposition: ApprovalDisposition): Promise<void> {
    if (!client || !snapshot) return; const approval = pendingApproval(snapshot); if (!approval) return;
    try { const response = await decidePendingApproval(client, snapshot.session.session_id, approval, disposition, disposition === "APPROVE" ? "approved from IDE" : "rejected from IDE"); setSnapshot(response.snapshot); setNotice(response.text || `[${response.stop_reason}]`); } catch (error) { setNotice(`无法提交决定：${String(error)}`); }
  }

  return <div className="app-shell"><WindowBar shell={shell} phase={phase} onSwitch={() => void switchWindow()} />{shell.surface === "agent" ? <AgentSurface onOpenSession={() => void openSession()} snapshot={snapshot} notice={notice} /> : <div className="ide-shell"><ActivityRail active={activity} onChange={setActivity} /><Explorer files={files} workspace={shell.workspace} onOpenFolder={() => void requestWorkspace()} /><section className="workbench"><div className="workbench-title"><span>{snapshot ? `工作 ${snapshot.session.task_id}` : "IDE"}</span><small>{statusCopy}</small></div><div className="editor-region">{!shell.workspace ? <WelcomeEditor onOpenFolder={() => void requestWorkspace()} onNewWork={() => void openSession()} /> : <EditorCanvas files={files} workspace={shell.workspace} />}</div><BottomPanel tab={panelTab} onTab={setPanelTab} terminal={terminal} diffs={diffs} /></section><AgentPanel thread={thread} snapshot={snapshot} draft={draft} notice={notice} onDraft={setDraft} onSend={() => void sendTurn()} onApprove={() => void decideApproval("APPROVE")} onReject={() => void decideApproval("REJECT")} /><footer className="status-bar"><span>⑂ main</span><span>⟳</span><span className="status-spacer" /><span>UTF-8</span><span>Spaces: 2</span><span>{phase.kind === "ready" ? "Agent OS 已连接" : "离线"}</span></footer></div>}</div>;
}
