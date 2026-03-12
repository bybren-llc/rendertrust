// MIT License -- see LICENSE-MIT

function DashboardPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Dashboard</h1>
        <p className="mt-1 text-sm text-gray-500">
          Welcome to RenderTrust Creator. Monitor your render jobs, manage
          credits, and configure your workspace.
        </p>
      </div>

      {/* Placeholder stats grid */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <div className="rounded-lg border border-gray-200 bg-white p-6">
          <p className="text-sm font-medium text-gray-500">Active Jobs</p>
          <p className="mt-2 text-3xl font-semibold text-gray-900">--</p>
        </div>
        <div className="rounded-lg border border-gray-200 bg-white p-6">
          <p className="text-sm font-medium text-gray-500">Credits Balance</p>
          <p className="mt-2 text-3xl font-semibold text-gray-900">--</p>
        </div>
        <div className="rounded-lg border border-gray-200 bg-white p-6">
          <p className="text-sm font-medium text-gray-500">Completed Jobs</p>
          <p className="mt-2 text-3xl font-semibold text-gray-900">--</p>
        </div>
      </div>

      <div className="rounded-lg border border-dashed border-gray-300 bg-white p-12 text-center">
        <p className="text-sm text-gray-400">
          Dashboard widgets will be implemented in future stories.
        </p>
      </div>
    </div>
  );
}

export default DashboardPage;
