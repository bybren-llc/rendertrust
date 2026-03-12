// MIT License -- see LICENSE-MIT

function CreditsPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Credits</h1>
        <p className="mt-1 text-sm text-gray-500">
          View your credit balance, purchase credits, and review transaction
          history.
        </p>
      </div>

      <div className="rounded-lg border border-gray-200 bg-white p-6">
        <p className="text-sm font-medium text-gray-500">Current Balance</p>
        <p className="mt-2 text-3xl font-semibold text-gray-900">-- credits</p>
      </div>

      <div className="rounded-lg border border-dashed border-gray-300 bg-white p-12 text-center">
        <p className="text-sm text-gray-400">
          Credit purchase and transaction history will be implemented in future
          stories.
        </p>
      </div>
    </div>
  );
}

export default CreditsPage;
