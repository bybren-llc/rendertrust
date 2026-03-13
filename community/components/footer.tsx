// Copyright (c) 2025 Words To Film By, Inc.
// Licensed under the MIT License. See LICENSE-MIT for details.

/**
 * Footer component for the community portal.
 */
export function Footer() {
  return (
    <footer className="border-t border-gray-200 bg-gray-50 py-8">
      <div className="mx-auto max-w-6xl px-4">
        <div className="flex flex-col items-center gap-4 sm:flex-row sm:justify-between">
          <div className="flex items-center gap-2">
            <span className="text-lg font-bold text-brand-900">
              RenderTrust
            </span>
            <span className="text-sm text-gray-500">Community Portal</span>
          </div>
          <div className="flex items-center gap-6 text-sm text-gray-500">
            <a
              href="https://rendertrust.com"
              target="_blank"
              rel="noopener noreferrer"
              className="hover:text-brand-600 transition-colors"
            >
              Website
            </a>
            <a
              href="https://docs.rendertrust.com"
              target="_blank"
              rel="noopener noreferrer"
              className="hover:text-brand-600 transition-colors"
            >
              Documentation
            </a>
            <a
              href="https://github.com/ByBren-LLC/rendertrust"
              target="_blank"
              rel="noopener noreferrer"
              className="hover:text-brand-600 transition-colors"
            >
              GitHub
            </a>
          </div>
        </div>
        <p className="mt-4 text-center text-xs text-gray-400">
          Copyright {new Date().getFullYear()} ByBren, LLC. All rights reserved.
        </p>
      </div>
    </footer>
  );
}
