/**
 * `noem self-update` — the upgrade path, exercised end to end against sources
 * this file controls.
 *
 * Every test serves its artifact from a temp directory (`file://`) or from a
 * loopback HTTP stub bound to an EPHEMERAL port (`listen(0)`); no test touches
 * the network, a real repository release, or the operator's `~/.agent-os`.
 *
 * The tests that matter most are the ones that could pass vacuously:
 *   - "checksum mismatch" is the bypass detector: delete the comparison in
 *     `runSelfUpdate` and it fails, because the corrupted artifact then gets
 *     installed. It asserts the installed bytes are UNCHANGED, not just that a
 *     status string came back.
 *   - "rollback" installs a real, deliberately broken artifact that passes
 *     shape and checksum, then asserts the PREVIOUS BYTES are back on disk AND
 *     still answer `--version` — a status assertion alone would not prove it.
 *     No test pins WHICH rejection kind (`spawn_error` vs `exit_nonzero`) the
 *     host reports for a file it will not run: that kind is platform-dependent
 *     (macOS fails the spawn, Linux's `execvp` retries the file as
 *     `/bin/sh <file>` and it exits non-zero), both mean "it did not run", and
 *     pinning one is what made this suite green on macOS and red on Linux. The
 *     decision logic is covered on every platform by INJECTING the kind.
 *   - "--check downloads nothing" points the manifest at an artifact that does
 *     not exist, so a check mode that quietly downloaded would report
 *     `source_unreachable` instead of `update_available`.
 */
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { chmodSync, existsSync, mkdtempSync, readFileSync, realpathSync, rmSync, statSync, writeFileSync } from "node:fs";
import { createServer, type Server } from "node:http";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import {
  BACKUP_SUFFIX,
  compareVersions,
  defaultInstallTarget,
  JOURNAL_SUFFIX,
  MANIFEST_FILE,
  parseVersion,
  readManifest,
  renderSelfUpdateText,
  runSelfUpdate,
  runSelfUpdateStatus,
  SELF_UPDATE_JOURNAL_SCHEMA,
  SELF_UPDATE_MANIFEST_SCHEMA,
  sourceUrl,
  STAGED_SUFFIX,
  type SanityRejection,
  type SelfUpdateDeps,
  type SelfUpdateReport,
  type SelfUpdateStatus,
} from "../src/self-update.js";

// The manifest's platform key is pinned so the fixtures are the same on any
// machine; the real default is `${process.platform}-${process.arch}`.
const PLATFORM = "test-platform";
const CURRENT = "0.1.0";
/** The key a CLI subprocess resolves for itself, which is the real machine's. */
const REAL_PLATFORM = `${process.platform}-${process.arch}`;

function tempDir(prefix: string): string {
  return mkdtempSync(join(tmpdir(), prefix));
}

function sha256(bytes: Uint8Array | string): string {
  return createHash("sha256").update(bytes).digest("hex");
}

/** A stand-in install: an executable shell script that answers `--version`. */
function program(version: string): Buffer {
  return Buffer.from(`#!/bin/sh\necho "${version}"\n`, "utf8");
}

function installFixture(version = CURRENT): { dir: string; target: string; original: Buffer } {
  const dir = tempDir("noem-selfupdate-install-");
  const target = join(dir, "noem");
  const original = program(version);
  writeFileSync(target, original, { mode: 0o755 });
  chmodSync(target, 0o755);
  return { dir, target, original };
}

interface PublishOptions {
  version?: string;
  artifact?: Uint8Array;
  artifactName?: string;
  /** `undefined` publishes the artifact's real digest; `null` omits the field. */
  sha256?: string | null;
  bytes?: number | null;
  platform?: string;
  /** Write this manifest verbatim instead of building one. */
  raw?: string;
  /** Do not write the artifact file at all (used by the `--check` test). */
  omitArtifact?: boolean;
}

interface Published {
  dir: string;
  source: string;
  artifactName: string;
  artifactPath: string;
  manifestPath: string;
  artifactBytes: Uint8Array;
}

function publish(options: PublishOptions = {}): Published {
  const dir = tempDir("noem-selfupdate-source-");
  const version = options.version ?? "0.2.0";
  const artifactName = options.artifactName ?? `noem-${version}-${PLATFORM}`;
  const artifactBytes = options.artifact ?? program(version);
  const artifactPath = join(dir, artifactName);
  if (options.omitArtifact !== true) writeFileSync(artifactPath, artifactBytes);

  const manifest =
    options.raw ??
    `${JSON.stringify(
      {
        schema: SELF_UPDATE_MANIFEST_SCHEMA,
        version,
        artifacts: {
          [options.platform ?? PLATFORM]: {
            file: artifactName,
            ...(options.sha256 === null ? {} : { sha256: options.sha256 ?? sha256(artifactBytes) }),
            ...(options.bytes === undefined || options.bytes === null ? {} : { bytes: options.bytes }),
          },
        },
      },
      null,
      2,
    )}\n`;
  const manifestPath = join(dir, MANIFEST_FILE);
  writeFileSync(manifestPath, manifest);
  return { dir, source: `file://${dir}`, artifactName, artifactPath, manifestPath, artifactBytes };
}

function deps(extra: Partial<SelfUpdateDeps> = {}): SelfUpdateDeps {
  return { platform: PLATFORM, currentVersion: () => CURRENT, ...extra };
}

/** Read one report's typed status; a one-line alias keeps assertions readable. */
function statusOf(report: SelfUpdateReport): SelfUpdateStatus {
  return report.status;
}

/** Every fixture is removed, and any read-only directory is made writable again first. */
function cleanup(...dirs: string[]): void {
  for (const dir of dirs) {
    try {
      chmodSync(dir, 0o755);
      rmSync(dir, { recursive: true, force: true });
    } catch {
      // a leftover temp dir is not a test failure
    }
  }
}

// ---------------------------------------------------------------------------
// Version ordering
// ---------------------------------------------------------------------------

test("parseVersion accepts X.Y.Z with prerelease/build and rejects anything else", () => {
  assert.deepEqual(parseVersion("1.2.3"), { major: 1, minor: 2, patch: 3, prerelease: null });
  assert.deepEqual(parseVersion(" 0.2.0-rc.1+build.5 "), {
    major: 0,
    minor: 2,
    patch: 0,
    prerelease: "rc.1",
  });
  for (const bad of ["", "1.2", "1.2.3.4", "v1.2.3", "1.2.x", "abc", "1.2.3-"]) {
    assert.equal(parseVersion(bad), null, `${JSON.stringify(bad)} must not parse`);
  }
});

test("compareVersions orders by field, and a prerelease ranks below its release", () => {
  assert.equal(compareVersions("0.2.0", "0.1.0"), 1);
  assert.equal(compareVersions("0.1.0", "0.2.0"), -1);
  assert.equal(compareVersions("0.1.0", "0.1.0"), 0);
  assert.equal(compareVersions("0.10.0", "0.9.9"), 1);
  assert.equal(compareVersions("1.0.0", "1.0.0-rc.1"), 1);
  assert.equal(compareVersions("1.0.0-rc.1", "1.0.0-rc.2"), -1);
  assert.equal(compareVersions("1.0.0-alpha", "1.0.0-beta"), -1);
  assert.equal(compareVersions("not-a-version", "1.0.0"), null);
});

// ---------------------------------------------------------------------------
// Inert by default
// ---------------------------------------------------------------------------

test("no source named: typed refusal, and nothing is fetched or written", async () => {
  const { dir, target, original } = installFixture();
  let fetches = 0;
  try {
    const report = await runSelfUpdate({
      target,
      env: {},
      deps: deps({
        fetchBytes: async () => {
          fetches += 1;
          throw new Error("must not be called");
        },
      }),
    });
    assert.equal(statusOf(report), "no_source_configured");
    assert.equal(report.exitCode, 2);
    assert.equal(report.ok, false);
    assert.equal(fetches, 0, "an unconfigured self-update must not reach the network");
    assert.deepEqual(readFileSync(target), original, "the install must be byte-identical");
    assert.ok(!existsSync(`${target}${STAGED_SUFFIX}`));
    assert.ok(!existsSync(`${target}${BACKUP_SUFFIX}`));
    assert.ok(!existsSync(`${target}${JOURNAL_SUFFIX}`));
    assert.match(report.detail, /no default release channel/);
  } finally {
    cleanup(dir);
  }
});

test("the source can come from the env, but only when the operator set it", async () => {
  const { dir, target } = installFixture();
  const published = publish();
  try {
    const report = await runSelfUpdate({
      target,
      env: { AGENT_OS_SELF_UPDATE_SOURCE: published.source },
      deps: deps(),
    });
    assert.equal(statusOf(report), "updated");
  } finally {
    cleanup(dir, published.dir);
  }
});

test("source of an unsupported scheme is refused before any install path is touched", async () => {
  const { dir, target, original } = installFixture();
  try {
    const report = await runSelfUpdate({
      target,
      source: "ftp://example.invalid/releases",
      env: {},
      deps: deps(),
    });
    assert.equal(statusOf(report), "source_invalid");
    assert.equal(report.exitCode, 2);
    assert.deepEqual(readFileSync(target), original);
  } finally {
    cleanup(dir);
  }
});

test("a script run under an interpreter has no derivable install path", async () => {
  // This test process is `node running a .ts file`, not a compiled binary.
  assert.equal(defaultInstallTarget(), null);
  const published = publish();
  try {
    const report = await runSelfUpdate({ source: published.source, env: {}, deps: deps() });
    assert.equal(statusOf(report), "target_unresolved");
    assert.equal(report.exitCode, 2);
    assert.match(report.detail, /--target/);
  } finally {
    cleanup(published.dir);
  }
});

test("a --target that is not an existing regular file is refused", async () => {
  const published = publish();
  const dir = tempDir("noem-selfupdate-missing-");
  try {
    const missing = await runSelfUpdate({
      source: published.source,
      target: join(dir, "absent"),
      env: {},
      deps: deps(),
    });
    assert.equal(statusOf(missing), "target_unresolved");

    const asDir = await runSelfUpdate({ source: published.source, target: dir, env: {}, deps: deps() });
    assert.equal(statusOf(asDir), "target_unresolved");
    assert.match(asDir.detail, /not a regular file/);
  } finally {
    cleanup(dir, published.dir);
  }
});

// ---------------------------------------------------------------------------
// The happy path
// ---------------------------------------------------------------------------

test("file:// source: the install is replaced and the new bytes answer --version", async () => {
  const { dir, target, original } = installFixture();
  const published = publish({ version: "0.2.0" });
  try {
    const report = await runSelfUpdate({ source: published.source, target, env: {}, deps: deps() });
    assert.equal(statusOf(report), "updated");
    assert.equal(report.exitCode, 0);
    assert.equal(report.ok, true);
    assert.equal(report.fromVersion, "0.1.0");
    assert.equal(report.toVersion, "0.2.0");
    assert.equal(report.measuredSha256, sha256(published.artifactBytes));
    assert.equal(report.bytes, published.artifactBytes.length);

    // The file on disk is the published artifact, and it RUNS.
    assert.deepEqual(readFileSync(target), Buffer.from(published.artifactBytes));
    const probe = spawnSync(target, ["--version"], { encoding: "utf8" });
    assert.equal(probe.status, 0);
    assert.equal(probe.stdout.trim(), "0.2.0");

    // The previous bytes are kept as the manual restore point; the staging file
    // and the journal are gone.
    assert.deepEqual(readFileSync(`${target}${BACKUP_SUFFIX}`), original);
    assert.ok(!existsSync(`${target}${STAGED_SUFFIX}`));
    assert.ok(!existsSync(`${target}${JOURNAL_SUFFIX}`));
    assert.equal(statSync(target).mode & 0o111, 0o111, "the replacement must stay executable");
    assert.match(renderSelfUpdateText(report), /no governance object was touched/);
  } finally {
    cleanup(dir, published.dir);
  }
});

test("loopback HTTP source on an ephemeral port: the install is replaced", async () => {
  const { dir, target } = installFixture();
  const artifact = program("0.3.0");
  const manifest = `${JSON.stringify({
    schema: SELF_UPDATE_MANIFEST_SCHEMA,
    version: "0.3.0",
    artifacts: { [PLATFORM]: { file: "noem-0.3.0", sha256: sha256(artifact) } },
  })}\n`;
  const server = await serve({ [`/${MANIFEST_FILE}`]: manifest, "/noem-0.3.0": artifact });
  try {
    assert.ok(server.port > 1024, `expected an ephemeral port, got ${server.port}`);
    const report = await runSelfUpdate({
      source: server.origin,
      target,
      env: {},
      deps: deps(),
    });
    assert.equal(statusOf(report), "updated");
    assert.equal(spawnSync(target, ["--version"], { encoding: "utf8" }).stdout.trim(), "0.3.0");
  } finally {
    await server.close();
    cleanup(dir);
  }
});

// ---------------------------------------------------------------------------
// Integrity — the bypass detectors
// ---------------------------------------------------------------------------

test("checksum mismatch: the artifact is refused and the install is left byte-identical", async () => {
  const { dir, target, original } = installFixture();
  // Publish the checksum of the GOOD artifact, then serve different bytes.
  const published = publish({ version: "0.2.0", artifact: program("0.2.0") });
  writeFileSync(published.artifactPath, program("9.9.9"));
  try {
    const report = await runSelfUpdate({ source: published.source, target, env: {}, deps: deps() });
    assert.equal(statusOf(report), "checksum_mismatch");
    assert.equal(report.exitCode, 1);
    assert.equal(report.expectedSha256, sha256(published.artifactBytes));
    assert.notEqual(report.measuredSha256, report.expectedSha256);
    assert.deepEqual(readFileSync(target), original, "a failed checksum must not install anything");
    assert.ok(!existsSync(`${target}${STAGED_SUFFIX}`), "the staged bytes must be removed");
    assert.ok(!existsSync(`${target}${BACKUP_SUFFIX}`));
  } finally {
    cleanup(dir, published.dir);
  }
});

test("a checksum that differs in its LAST nibble is still a mismatch", async () => {
  const { dir, target, original } = installFixture();
  const published = publish({ version: "0.2.0" });
  // Distance from the true digest: one character. Any comparison that ignores
  // part of the digest — or compares a prefix of it — accepts this.
  const trueDigest = sha256(published.artifactBytes);
  const nearMiss = `${trueDigest.slice(0, 63)}${trueDigest[63] === "0" ? "1" : "0"}`;
  writeFileSync(
    published.manifestPath,
    `${JSON.stringify({
      schema: SELF_UPDATE_MANIFEST_SCHEMA,
      version: "0.2.0",
      artifacts: { [PLATFORM]: { file: published.artifactName, sha256: nearMiss } },
    })}\n`,
  );
  try {
    const report = await runSelfUpdate({ source: published.source, target, env: {}, deps: deps() });
    assert.equal(statusOf(report), "checksum_mismatch", "the WHOLE digest must be compared");
    assert.equal(report.expectedSha256, nearMiss);
    assert.equal(report.measuredSha256, trueDigest);
    assert.deepEqual(readFileSync(target), original);
  } finally {
    cleanup(dir, published.dir);
  }
});

test("checksum mismatch detected when the manifest's byte count disagrees with what was served", async () => {
  const { dir, target, original } = installFixture();
  const published = publish({ version: "0.2.0", bytes: 999_999 });
  try {
    const report = await runSelfUpdate({ source: published.source, target, env: {}, deps: deps() });
    assert.equal(statusOf(report), "checksum_mismatch");
    assert.deepEqual(readFileSync(target), original);
  } finally {
    cleanup(dir, published.dir);
  }
});

test("checksum missing: an unverifiable artifact is refused, not installed", async () => {
  const { dir, target, original } = installFixture();
  const published = publish({ version: "0.2.0", sha256: null });
  try {
    const report = await runSelfUpdate({ source: published.source, target, env: {}, deps: deps() });
    assert.equal(statusOf(report), "checksum_missing");
    assert.match(report.detail, /unverifiable artifact is refused/);
    assert.deepEqual(readFileSync(target), original);
  } finally {
    cleanup(dir, published.dir);
  }
});

test("a malformed sha256 is a manifest error, not a silent skip of verification", () => {
  const read = readManifest(
    `${JSON.stringify({
      schema: SELF_UPDATE_MANIFEST_SCHEMA,
      version: "0.2.0",
      artifacts: { [PLATFORM]: { file: "noem", sha256: "not-a-digest" } },
    })}`,
    PLATFORM,
  );
  assert.equal(read.status, "manifest_invalid");
  assert.equal(read.artifact, null);
});

test("the manifest cannot point the download outside the source directory", () => {
  const read = readManifest(
    `${JSON.stringify({
      schema: SELF_UPDATE_MANIFEST_SCHEMA,
      version: "0.2.0",
      artifacts: { [PLATFORM]: { file: "../../etc/passwd", sha256: sha256("x") } },
    })}`,
    PLATFORM,
  );
  assert.equal(read.status, "manifest_invalid");
  assert.match(read.detail, /bare file name/);
});

// ---------------------------------------------------------------------------
// Other refusals
// ---------------------------------------------------------------------------

test("unreachable source: a missing manifest, and an HTTP 404", async () => {
  const { dir, target, original } = installFixture();
  const empty = tempDir("noem-selfupdate-empty-");
  const server = await serve({ "/other": "nothing" });
  try {
    const missing = await runSelfUpdate({ source: `file://${empty}`, target, env: {}, deps: deps() });
    assert.equal(statusOf(missing), "source_unreachable");
    assert.match(missing.detail, /manifest\.json/);

    const http404 = await runSelfUpdate({ source: server.origin, target, env: {}, deps: deps() });
    assert.equal(statusOf(http404), "source_unreachable");
    assert.match(http404.detail, /HTTP 404/);
    assert.deepEqual(readFileSync(target), original);
  } finally {
    await server.close();
    cleanup(dir, empty);
  }
});

test("an artifact that cannot be read is a source error, not a partial install", async () => {
  const { dir, target, original } = installFixture();
  const published = publish({ version: "0.2.0", omitArtifact: true });
  try {
    const report = await runSelfUpdate({ source: published.source, target, env: {}, deps: deps() });
    assert.equal(statusOf(report), "source_unreachable");
    assert.deepEqual(readFileSync(target), original);
  } finally {
    cleanup(dir, published.dir);
  }
});

test("malformed manifests are typed manifest_invalid, never a crash", async () => {
  const { dir, target, original } = installFixture();
  const cases: { raw: string; why: string }[] = [
    { raw: "}{", why: "not JSON" },
    { raw: `${JSON.stringify({ schema: "something-else/9", version: "0.2.0", artifacts: {} })}`, why: "wrong schema" },
    { raw: `${JSON.stringify({ schema: SELF_UPDATE_MANIFEST_SCHEMA, version: "0.2.0" })}`, why: "no artifacts" },
    {
      raw: `${JSON.stringify({
        schema: SELF_UPDATE_MANIFEST_SCHEMA,
        version: "0.2.0",
        artifacts: { "other-platform": { file: "f", sha256: sha256("x") } },
      })}`,
      why: "no entry for this platform",
    },
    {
      raw: `${JSON.stringify({
        schema: SELF_UPDATE_MANIFEST_SCHEMA,
        version: "two",
        artifacts: { [PLATFORM]: { file: "f", sha256: sha256("x") } },
      })}`,
      why: "unparseable version",
    },
  ];
  try {
    for (const scenario of cases) {
      const published = publish({ raw: scenario.raw });
      try {
        const report = await runSelfUpdate({ source: published.source, target, env: {}, deps: deps() });
        assert.equal(statusOf(report), "manifest_invalid", scenario.why);
        assert.deepEqual(readFileSync(target), original, scenario.why);
      } finally {
        cleanup(published.dir);
      }
    }
  } finally {
    cleanup(dir);
  }
});

test("a downgrade is refused, and the equal version is up_to_date", async () => {
  const { dir, target, original } = installFixture();
  const older = publish({ version: "0.0.9" });
  const same = publish({ version: CURRENT });
  try {
    const downgrade = await runSelfUpdate({ source: older.source, target, env: {}, deps: deps() });
    assert.equal(statusOf(downgrade), "downgrade_refused");
    assert.equal(downgrade.exitCode, 1);
    assert.match(downgrade.detail, /OLDER/);
    assert.deepEqual(readFileSync(target), original);

    const current = await runSelfUpdate({ source: same.source, target, env: {}, deps: deps() });
    assert.equal(statusOf(current), "up_to_date");
    assert.equal(current.exitCode, 0);
    assert.deepEqual(readFileSync(target), original);
  } finally {
    cleanup(dir, older.dir, same.dir);
  }
});

test("a non-executable artifact is refused before the install is touched", async () => {
  const { dir, target, original } = installFixture();
  const cases: Uint8Array[] = [
    Buffer.alloc(0), // empty
    Buffer.from("this is a README, not a program image\n", "utf8"),
  ];
  try {
    for (const bytes of cases) {
      const published = publish({ version: "0.2.0", artifact: bytes });
      try {
        const report = await runSelfUpdate({ source: published.source, target, env: {}, deps: deps() });
        assert.equal(statusOf(report), "artifact_not_executable", `${bytes.length} bytes`);
        assert.deepEqual(readFileSync(target), original);
      } finally {
        cleanup(published.dir);
      }
    }
  } finally {
    cleanup(dir);
  }
});

test("--check reports availability, downloads no artifact, and installs nothing", async () => {
  const { dir, target, original } = installFixture();
  // The artifact is deliberately ABSENT: a --check that downloaded would fail.
  const published = publish({ version: "0.2.0", omitArtifact: true });
  const alreadyCurrent = publish({ version: CURRENT });
  try {
    const report = await runSelfUpdate({
      source: published.source,
      target,
      check: true,
      env: {},
      deps: deps(),
    });
    assert.equal(statusOf(report), "update_available");
    assert.equal(report.exitCode, 0);
    assert.equal(report.toVersion, "0.2.0");
    assert.match(report.detail, /--check downloaded nothing/);
    assert.deepEqual(readFileSync(target), original);
    assert.ok(!existsSync(`${target}${STAGED_SUFFIX}`));

    const stale = await runSelfUpdate({
      source: alreadyCurrent.source,
      target,
      check: true,
      env: {},
      deps: deps(),
    });
    assert.equal(statusOf(stale), "up_to_date");
  } finally {
    cleanup(dir, published.dir, alreadyCurrent.dir);
  }
});

// ---------------------------------------------------------------------------
// Rollback — the failure paths that must not leave the install broken
// ---------------------------------------------------------------------------

/**
 * The rejection kinds that both mean "the new artifact did not run".
 *
 * WHICH of the two an OS reports is platform-dependent, so no test may pin one:
 *  - macOS does not retry a file the kernel will not execute, so the spawn
 *    fails outright -> `spawn_error` (measured: libc `execvp` there reports
 *    "Exec format error" instead of running it through a shell).
 *  - Linux spawns through glibc's `execvp`, which on `ENOEXEC` RETRIES the file
 *    as `/bin/sh <file>`. The process therefore DOES start — as a shell reading
 *    binary garbage — and exits non-zero -> `exit_nonzero`.
 * Pinning `spawn_error` here is exactly what made the truncated-Mach-O case
 * green on macOS and red on the Linux runner, while the product contract
 * ("rejected; previous install restored; restored binary still works") held on
 * both. Do NOT re-tighten this to a single kind; see `SanityRejection` in
 * `src/self-update.ts`.
 */
const DID_NOT_RUN: readonly SanityRejection[] = ["spawn_error", "exit_nonzero"];

test("rollback: a broken artifact is installed, caught by its own --version, and the previous bytes are restored", async () => {
  const { dir, target, original } = installFixture();
  // Passes the shape check (a shebang) and the checksum; fails when RUN.
  const broken = Buffer.from("#!/bin/sh\necho 'noem: broken build' >&2\nexit 9\n", "utf8");
  const published = publish({ version: "0.2.0", artifact: broken });
  try {
    const report = await runSelfUpdate({ source: published.source, target, env: {}, deps: deps() });
    assert.equal(statusOf(report), "rolled_back");
    assert.equal(report.exitCode, 1);
    assert.equal(report.ok, false);
    // Deterministic on every POSIX host, unlike DID_NOT_RUN: a shebang is
    // resolved by the KERNEL (binfmt_script), so the process always starts, runs
    // `/bin/sh`, and exits 9 — no platform-specific spawn path is involved.
    assert.equal(report.rejection, "exit_nonzero");
    assert.match(report.detail, /restored 0\.1\.0/);

    // The restore is real: the ORIGINAL BYTES are back AND they still run.
    assert.deepEqual(readFileSync(target), original);
    const probe = spawnSync(target, ["--version"], { encoding: "utf8" });
    assert.equal(probe.status, 0);
    assert.equal(probe.stdout.trim(), CURRENT);

    // The backup was consumed by the restore; nothing half-done is left behind.
    assert.ok(!existsSync(`${target}${BACKUP_SUFFIX}`));
    assert.ok(!existsSync(`${target}${STAGED_SUFFIX}`));
    assert.ok(!existsSync(`${target}${JOURNAL_SUFFIX}`));
  } finally {
    cleanup(dir, published.dir);
  }
});

test("rollback: a truncated Mach-O passes shape + checksum and is caught when executed", async () => {
  const { dir, target, original } = installFixture();
  // A real program-image magic with garbage after it: exactly what a truncated
  // or wrong-architecture artifact looks like, and unverifiable without exec.
  const truncated = Buffer.concat([Buffer.from([0xcf, 0xfa, 0xed, 0xfe]), Buffer.alloc(512, 0x00)]);
  const published = publish({ version: "0.2.0", artifact: truncated });
  try {
    const report = await runSelfUpdate({ source: published.source, target, env: {}, deps: deps() });
    // Assert the bytes reached the staged file, so the rejection below is from
    // EXECUTING them and not from an earlier gate failing first.
    assert.equal(report.measuredSha256, sha256(truncated), "the bytes must have passed shape + checksum");
    assert.equal(report.bytes, truncated.length);
    assert.equal(statusOf(report), "rolled_back");
    // The contract is "the artifact did not run and the install was rolled
    // back", NOT which way the host refused to run it — that kind is
    // platform-dependent (see DID_NOT_RUN). Asserting a single kind here is the
    // defect this test was fixed for: green on macOS, red on the Linux runner.
    assert.ok(
      report.rejection !== null && DID_NOT_RUN.includes(report.rejection),
      `the artifact must be rejected as un-runnable, got ${String(report.rejection)}: ${report.detail}`,
    );
    // Rollback is the part that matters, and it is asserted in full: the
    // ORIGINAL BYTES are back on disk AND they still run.
    assert.deepEqual(readFileSync(target), original);
    assert.equal(spawnSync(target, ["--version"], { encoding: "utf8" }).stdout.trim(), CURRENT);
    assert.ok(!existsSync(`${target}${BACKUP_SUFFIX}`));
    assert.ok(!existsSync(`${target}${STAGED_SUFFIX}`));
    assert.ok(!existsSync(`${target}${JOURNAL_SUFFIX}`));
  } finally {
    cleanup(dir, published.dir);
  }
});

/**
 * Both "did not run" kinds, INJECTED rather than produced by the host.
 *
 * A test that waits for the host OS to produce a kind can only ever prove one
 * platform's behaviour (that is precisely how the truncated-Mach-O case passed
 * on macOS while failing on Linux), so the decision logic is exercised here by
 * having the probe report each kind directly. `runSelfUpdate` promises the same
 * thing for both: reject the new bytes, restore the previous ones, verify the
 * restore. The restored-binary assertion still uses a real spawn, so the
 * rollback is proven by running a program, not by a status string.
 */
test("rollback: both un-runnable rejection kinds roll back identically", async () => {
  for (const kind of DID_NOT_RUN) {
    const { dir, target, original } = installFixture();
    const published = publish({ version: "0.2.0" });
    const probeDetail = `${kind}: injected — the candidate did not answer --version`;
    try {
      const report = await runSelfUpdate({
        source: published.source,
        target,
        env: {},
        deps: deps({
          // What the real probe does, minus the host: the bytes on disk answer
          // --version only while the ORIGINAL program is installed.
          probe: (path) => {
            const bytes = readFileSync(path);
            if (bytes.equals(original)) return { ok: true, version: CURRENT };
            return { ok: false, rejection: kind, detail: probeDetail };
          },
        }),
      });
      assert.equal(statusOf(report), "rolled_back", kind);
      assert.equal(report.rejection, kind, kind);
      assert.equal(report.exitCode, 1, kind);
      assert.equal(report.ok, false, kind);
      // The operator is shown what the probe reported, and nothing more: the
      // message must not assert an OS-level cause the code cannot know.
      assert.ok(report.detail.includes(probeDetail), `${kind}: ${report.detail}`);
      assert.match(report.detail, /restored 0\.1\.0/, kind);
      assert.deepEqual(readFileSync(target), original, kind);
      const restored = spawnSync(target, ["--version"], { encoding: "utf8" });
      assert.equal(restored.status, 0, kind);
      assert.equal(restored.stdout.trim(), CURRENT, kind);
      assert.ok(!existsSync(`${target}${BACKUP_SUFFIX}`), kind);
      assert.ok(!existsSync(`${target}${STAGED_SUFFIX}`), kind);
      assert.ok(!existsSync(`${target}${JOURNAL_SUFFIX}`), kind);
    } finally {
      cleanup(dir, published.dir);
    }
  }
});

test("rollback: a candidate that runs but reports the wrong version is rejected", async () => {
  const { dir, target, original } = installFixture();
  // Shape and checksum say 0.2.0; the program itself answers 0.4.0.
  const published = publish({ version: "0.2.0", artifact: program("0.4.0") });
  try {
    const report = await runSelfUpdate({ source: published.source, target, env: {}, deps: deps() });
    assert.equal(statusOf(report), "rolled_back");
    assert.equal(report.rejection, "version_mismatch");
    assert.match(report.detail, /answers 0\.4\.0/);
    assert.deepEqual(readFileSync(target), original);
  } finally {
    cleanup(dir, published.dir);
  }
});

test("rollback_failed is loud and names the backup when the previous bytes cannot be put back", async () => {
  const { dir, target, original } = installFixture();
  const backup = `${target}${BACKUP_SUFFIX}`;
  // A hostile/broken candidate: fails its probe AND destroys its own rollback
  // source first, the worst case the operator must be told about plainly.
  const saboteur = Buffer.from(
    `#!/bin/sh\nrm -f "$0${BACKUP_SUFFIX}"\necho "noem: sabotaged" >&2\nexit 1\n`,
    "utf8",
  );
  const published = publish({ version: "0.2.0", artifact: saboteur });
  try {
    const report = await runSelfUpdate({ source: published.source, target, env: {}, deps: deps() });
    assert.equal(statusOf(report), "rollback_failed");
    assert.equal(report.exitCode, 1);
    assert.equal(report.rejection, "exit_nonzero");
    assert.ok(report.detail.includes(backup), "the message must name the missing backup");
    assert.ok(report.detail.includes(`cp `), "the message must say how to restore by hand");
    // Honestly reported: the install path now holds the failed candidate.
    assert.notDeepEqual(readFileSync(target), original);
    assert.equal(spawnSync(target, ["--version"], { encoding: "utf8" }).status, 1);
  } finally {
    cleanup(dir, published.dir);
  }
});

test("replace_failed: an unwritable install directory leaves the program untouched", async () => {
  const { dir, target, original } = installFixture();
  const published = publish({ version: "0.2.0" });
  chmodSync(dir, 0o555); // not writable: staging must fail, nothing is replaced
  try {
    if (process.getuid?.() === 0) return; // root ignores the mode bits
    const report = await runSelfUpdate({ source: published.source, target, env: {}, deps: deps() });
    assert.equal(statusOf(report), "replace_failed");
    assert.equal(report.exitCode, 1);
    assert.deepEqual(readFileSync(target), original);
    assert.ok(!existsSync(`${target}${BACKUP_SUFFIX}`));
    assert.ok(!existsSync(`${target}${JOURNAL_SUFFIX}`));
  } finally {
    chmodSync(dir, 0o755);
    cleanup(dir, published.dir);
  }
});

// ---------------------------------------------------------------------------
// Interruption
// ---------------------------------------------------------------------------

function writeJournal(target: string, fields: Record<string, unknown>): string {
  const path = `${target}${JOURNAL_SUFFIX}`;
  writeFileSync(
    path,
    `${JSON.stringify({
      schema: SELF_UPDATE_JOURNAL_SCHEMA,
      pid: 4242,
      target,
      backup: `${target}${BACKUP_SUFFIX}`,
      from_version: CURRENT,
      to_version: "0.2.0",
      expected_sha256: sha256("x"),
      started_at: "2026-09-18T00:00:00.000Z",
      ...fields,
    })}\n`,
  );
  return path;
}

test("an interrupted run whose owner is still alive blocks a second one", async () => {
  const { dir, target, original } = installFixture();
  const published = publish({ version: "0.2.0" });
  const journal = writeJournal(target, {});
  try {
    const report = await runSelfUpdate({
      source: published.source,
      target,
      env: {},
      deps: deps({ pidAlive: () => true }),
    });
    assert.equal(statusOf(report), "interrupted_update_pending");
    assert.equal(report.exitCode, 1);
    assert.equal(report.interrupted?.resolution, "pending");
    assert.deepEqual(readFileSync(target), original);
    assert.ok(existsSync(journal), "the other run's journal must be left alone");
  } finally {
    cleanup(dir, published.dir);
  }
});

test("an interrupted run that never changed anything is cleaned up, then the update proceeds", async () => {
  const { dir, target } = installFixture(CURRENT);
  const published = publish({ version: "0.2.0" });
  writeJournal(target, {}); // from_version == what is installed
  try {
    const report = await runSelfUpdate({
      source: published.source,
      target,
      env: {},
      deps: deps({ pidAlive: () => false }),
    });
    assert.equal(statusOf(report), "updated");
    assert.equal(report.interrupted?.resolution, "cleaned");
    assert.ok(!existsSync(`${target}${JOURNAL_SUFFIX}`));
    assert.equal(spawnSync(target, ["--version"], { encoding: "utf8" }).stdout.trim(), "0.2.0");
  } finally {
    cleanup(dir, published.dir);
  }
});

test("an interrupted run whose replace landed is committed instead of re-installed", async () => {
  // The operator relaunched after the interrupted run, so the running process
  // already IS 0.2.0 — the journal's from_version is behind reality.
  const { dir, target } = installFixture("0.2.0");
  const published = publish({ version: "0.2.0" });
  writeJournal(target, {});
  try {
    const report = await runSelfUpdate({
      source: published.source,
      target,
      env: {},
      deps: deps({ pidAlive: () => false, currentVersion: () => "0.2.0" }),
    });
    assert.equal(statusOf(report), "up_to_date");
    assert.equal(report.interrupted?.resolution, "committed");
    assert.match(report.interrupted?.detail ?? "", /the replace landed/);
    assert.ok(!existsSync(`${target}${JOURNAL_SUFFIX}`));
  } finally {
    cleanup(dir, published.dir);
  }
});

test("an interrupted run that left a third, unrunnable program restores the backup", async () => {
  const { dir, target } = installFixture("7.7.7"); // neither from_version nor to_version
  const backup = `${target}${BACKUP_SUFFIX}`;
  writeFileSync(backup, program(CURRENT), { mode: 0o755 });
  const published = publish({ version: "0.2.0" });
  writeJournal(target, {});
  try {
    const report = await runSelfUpdate({
      source: published.source,
      target,
      env: {},
      deps: deps({ pidAlive: () => false }),
    });
    assert.equal(statusOf(report), "updated");
    assert.equal(report.interrupted?.resolution, "restored");
    assert.equal(spawnSync(target, ["--version"], { encoding: "utf8" }).stdout.trim(), "0.2.0");
  } finally {
    cleanup(dir, published.dir);
  }
});

test("an interrupted run with no usable backup is rollback_failed, not a guess", async () => {
  const { dir, target } = installFixture("7.7.7");
  const published = publish({ version: "0.2.0" });
  writeJournal(target, {});
  try {
    const report = await runSelfUpdate({
      source: published.source,
      target,
      env: {},
      deps: deps({ pidAlive: () => false }),
    });
    assert.equal(statusOf(report), "rollback_failed");
    assert.equal(report.interrupted?.resolution, "unrecoverable");
    assert.match(report.detail, /could not be resolved/);
  } finally {
    cleanup(dir, published.dir);
  }
});

// ---------------------------------------------------------------------------
// --status (read-only)
// ---------------------------------------------------------------------------

test("--status names the install, the source and any pending journal, and writes nothing", async () => {
  const { dir, target, original } = installFixture();
  try {
    const clean = runSelfUpdateStatus({
      target,
      env: {},
      deps: deps({ pidAlive: () => false }),
    });
    assert.equal(clean.ok, true);
    assert.equal(clean.currentVersion, CURRENT);
    // macOS resolves /var -> /private/var, so compare against the real path.
    assert.equal(clean.installPath, realpathSync(target));
    assert.equal(clean.source, null);
    assert.equal(clean.journal, null);

    const env = { AGENT_OS_SELF_UPDATE_SOURCE: "file:///srv/noem" };
    assert.equal(runSelfUpdateStatus({ target, env, deps: deps() }).source, "file:///srv/noem");

    writeJournal(target, { to_version: "0.2.0" });
    const pending = runSelfUpdateStatus({ target, env: {}, deps: deps({ pidAlive: () => false }) });
    assert.equal(pending.ok, false);
    assert.equal(pending.journal?.to_version, "0.2.0");
    assert.equal(pending.journalOwnerAlive, false);
    assert.deepEqual(readFileSync(target), original);
    assert.ok(existsSync(`${target}${JOURNAL_SUFFIX}`), "--status must not resolve anything");
  } finally {
    cleanup(dir);
  }
});

// ---------------------------------------------------------------------------
// The public entry point (CLI)
// ---------------------------------------------------------------------------

function runCli(args: string[], home: string): { code: number | null; out: string; err: string } {
  const result = spawnSync(process.execPath, ["--import", "tsx", "src/cli.tsx", ...args], {
    encoding: "utf8",
    env: { ...process.env, HOME: home, AGENT_OS_SELF_UPDATE_SOURCE: "" },
    cwd: new URL("..", import.meta.url).pathname,
  });
  return { code: result.status, out: result.stdout, err: result.stderr };
}

test("`noem self-update` with no source exits 2, explains why, and starts no daemon", () => {
  const home = tempDir("noem-selfupdate-home-");
  try {
    const result = runCli(["self-update"], home);
    assert.equal(result.code, 2);
    assert.match(result.out, /no_source_configured/);
    assert.match(result.out, /no default release channel/);
    assert.ok(!existsSync(join(home, ".agent-os", "runtime.json")), "must not autostart a daemon");
    assert.ok(
      !result.out.includes("native FFI"),
      "self-update must stay a lazily-imported, view-free path",
    );
  } finally {
    cleanup(home);
  }
});

test("`noem self-update --help` documents the explicit-source rule and exits 0", () => {
  const home = tempDir("noem-selfupdate-home-");
  try {
    const result = runCli(["self-update", "--help"], home);
    assert.equal(result.code, 0);
    assert.match(result.out, /--source <url>/);
    assert.match(result.out, /no default channel/);
    assert.match(result.out, /C7, permission modes, approval,/);
  } finally {
    cleanup(home);
  }
});

test("`noem self-update` end to end: replaces the target and prints a JSON report", () => {
  const home = tempDir("noem-selfupdate-home-");
  const { dir, target } = installFixture();
  // The subprocess resolves its own platform key, so publish for the real one.
  const published = publish({ version: "0.2.0", platform: REAL_PLATFORM });
  try {
    const result = runCli(
      ["self-update", "--source", published.source, "--target", target, "--json"],
      home,
    );
    assert.equal(result.code, 0, result.out + result.err);
    const parsed = JSON.parse(result.out) as SelfUpdateReport;
    assert.equal(parsed.status, "updated");
    assert.equal(parsed.toVersion, "0.2.0");
    assert.equal(spawnSync(target, ["--version"], { encoding: "utf8" }).stdout.trim(), "0.2.0");
    assert.ok(!existsSync(join(home, ".agent-os", "runtime.json")));
    // The trace line on stderr is machine-readable and is not a receipt.
    assert.equal((JSON.parse(result.err.trim()) as { event: string }).event, "self_update");
  } finally {
    cleanup(home, dir, published.dir);
  }
});

test("`noem self-update --status` is read-only and exits 0", () => {
  const home = tempDir("noem-selfupdate-home-");
  const { dir, target, original } = installFixture();
  try {
    const result = runCli(["self-update", "--status", "--target", target], home);
    assert.equal(result.code, 0);
    assert.match(result.out, /noem 0\.1\.0/);
    assert.match(result.out, /no interrupted run/);
    assert.deepEqual(readFileSync(target), original);
  } finally {
    cleanup(home, dir);
  }
});

// ---------------------------------------------------------------------------
// Local HTTP stub
// ---------------------------------------------------------------------------

async function serve(files: Record<string, string | Uint8Array>): Promise<{
  origin: string;
  port: number;
  close: () => Promise<void>;
}> {
  const server: Server = createServer((request, response) => {
    const body = files[request.url ?? ""];
    if (body === undefined) {
      response.writeHead(404, { "content-type": "text/plain" });
      response.end("not found");
      return;
    }
    response.writeHead(200, { "content-type": "application/octet-stream" });
    response.end(body);
  });
  // Port 0: the OS assigns a free ephemeral port, so two workstreams cannot
  // collide on a fixed number.
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const address = server.address();
  if (address === null || typeof address === "string") throw new Error("no port assigned");
  return {
    origin: `http://127.0.0.1:${address.port}`,
    port: address.port,
    close: () => new Promise<void>((resolve) => server.close(() => resolve())),
  };
}

test("sourceUrl joins a source treated as a directory, with or without a trailing slash", () => {
  assert.equal(sourceUrl("file:///srv/noem", MANIFEST_FILE), "file:///srv/noem/manifest.json");
  assert.equal(sourceUrl("file:///srv/noem/", MANIFEST_FILE), "file:///srv/noem/manifest.json");
  assert.equal(sourceUrl("https://example.invalid/r", "noem-1"), "https://example.invalid/r/noem-1");
});
