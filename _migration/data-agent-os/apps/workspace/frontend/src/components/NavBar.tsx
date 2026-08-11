'use client';

import { useState } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useAppStore } from '@/lib/store';

const navItems = [
  { href: '/', label: 'Workspace' },
  { href: '/workspace', label: 'NL Workspace' },
  { href: '/runs', label: 'Runs' },
  { href: '/trace', label: 'Trace' },
  { href: '/knowledge', label: 'Knowledge' },
  { href: '/approvals', label: 'Approvals' },
  { href: '/outcomes', label: 'Outcomes' },
];

export function NavBar() {
  const pathname = usePathname();
  const [settingsOpen, setSettingsOpen] = useState(false);
  const { apiUrl, apiKey, operatorKey, setApiUrl, setApiKey, setOperatorKey } = useAppStore();
  const [localApiUrl, setLocalApiUrl] = useState(apiUrl);
  const [localApiKey, setLocalApiKey] = useState(apiKey);
  const [localOperatorKey, setLocalOperatorKey] = useState(operatorKey);

  const handleSaveSettings = () => {
    setApiUrl(localApiUrl);
    setApiKey(localApiKey);
    setOperatorKey(localOperatorKey);
    setSettingsOpen(false);
  };

  const isActive = (href: string) => {
    if (href === '/') return pathname === '/';
    return pathname.startsWith(href);
  };

  return (
    <header className="relative z-30 border-b border-gray-800 bg-gray-900">
      <div className="mx-auto flex h-14 max-w-[1600px] items-center justify-between px-6">
        {/* Left: logo + nav */}
        <div className="flex items-center gap-8">
          <Link href="/" className="flex items-center gap-2">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-blue-600">
              <span className="text-sm font-bold text-white">DA</span>
            </div>
            <span className="text-sm font-semibold text-white hidden sm:inline">
              Data Agent OS
            </span>
          </Link>
          <nav className="flex items-center gap-1">
            {navItems.map((item) => (
              <Link
                key={item.href}
                href={item.href}
                className={`rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
                  isActive(item.href)
                    ? 'bg-gray-800 text-white'
                    : 'text-gray-400 hover:bg-gray-800 hover:text-gray-200'
                }`}
              >
                {item.label}
              </Link>
            ))}
          </nav>
        </div>

        {/* Right: settings */}
        <div className="relative">
          <button
            onClick={() => setSettingsOpen(!settingsOpen)}
            className="rounded-md p-2 text-gray-400 hover:bg-gray-800 hover:text-gray-200 transition-colors"
            aria-label="Settings"
          >
            <svg
              xmlns="http://www.w3.org/2000/svg"
              viewBox="0 0 20 20"
              fill="currentColor"
              className="h-5 w-5"
            >
              <path
                fillRule="evenodd"
                d="M7.84 1.804A1 1 0 018.82 1h2.36a1 1 0 01.98.804l.331 1.652a6.993 6.993 0 011.929 1.115l1.598-.54a1 1 0 011.186.447l1.18 2.044a1 1 0 01-.205 1.251l-1.267 1.113a7.047 7.047 0 010 2.228l1.267 1.113a1 1 0 01.206 1.25l-1.18 2.045a1 1 0 01-1.187.447l-1.598-.54a6.993 6.993 0 01-1.929 1.115l-.33 1.652a1 1 0 01-.98.804H8.82a1 1 0 01-.98-.804l-.331-1.652a6.993 6.993 0 01-1.929-1.115l-1.598.54a1 1 0 01-1.186-.447l-1.18-2.044a1 1 0 01.205-1.251l1.267-1.113a7.05 7.05 0 010-2.228l-1.267-1.113a1 1 0 01-.206-1.25l1.18-2.045a1 1 0 011.187-.447l1.598.54a6.993 6.993 0 011.929-1.115l.33-1.652zM11 6a4 4 0 100 8 4 4 0 000-8z"
                clipRule="evenodd"
              />
            </svg>
          </button>

          {settingsOpen && (
            <div className="absolute right-0 top-full mt-2 w-80 rounded-lg border border-gray-700 bg-gray-800 p-4 shadow-xl">
              <h3 className="text-sm font-semibold text-white mb-3">Connection Settings</h3>
              <div className="space-y-3">
                <div>
                  <label className="block text-xs font-medium text-gray-400 mb-1">
                    API URL
                  </label>
                  <input
                    type="text"
                    value={localApiUrl}
                    onChange={(e) => setLocalApiUrl(e.target.value)}
                    className="w-full rounded-md border border-gray-600 bg-gray-700 px-3 py-1.5 text-sm text-white placeholder-gray-400 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                    placeholder="http://localhost:8000"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-400 mb-1">
                    API Key
                  </label>
                  <input
                    type="password"
                    value={localApiKey}
                    onChange={(e) => setLocalApiKey(e.target.value)}
                    className="w-full rounded-md border border-gray-600 bg-gray-700 px-3 py-1.5 text-sm text-white placeholder-gray-400 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                    placeholder="Your API key"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-400 mb-1">
                    Operator Key
                  </label>
                  <input
                    type="password"
                    value={localOperatorKey}
                    onChange={(e) => setLocalOperatorKey(e.target.value)}
                    className="w-full rounded-md border border-gray-600 bg-gray-700 px-3 py-1.5 text-sm text-white placeholder-gray-400 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                    placeholder="Your operator key"
                  />
                </div>
                <button
                  onClick={handleSaveSettings}
                  className="w-full rounded-md bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700 transition-colors"
                >
                  Save
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </header>
  );
}
