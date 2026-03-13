// MIT License -- see LICENSE-MIT
//
// Job list page -- displays all user jobs in a table with status badges,
// auto-refresh polling, and action buttons.

import { useCallback, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useJobs, useCancelJob } from "../../hooks/useJobs";
import type { JobStatus } from "../../lib/jobs";
import {
  isJobCancellable,
  statusBadgeClasses,
  statusLabel,
} from "../../lib/jobs";

// ---------------------------------------------------------------------------
// Status filter options
// ---------------------------------------------------------------------------

const STATUS_FILTERS: { value: JobStatus | "ALL"; label: string }[] = [
  { value: "ALL", label: "All" },
  { value: "QUEUED", label: "Queued" },
  { value: "DISPATCHED", label: "Dispatched" },
  { value: "RUNNING", label: "Running" },
  { value: "COMPLETED", label: "Completed" },
  { value: "FAILED", label: "Failed" },
];

// ---------------------------------------------------------------------------
// Helper -- format timestamp to short local string
// ---------------------------------------------------------------------------

function formatTimestamp(iso: string): string {
  try {
    const d = new Date(iso);
    return d.toLocaleString(undefined, {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

/** Truncate a UUID to first 8 chars for display. */
function shortId(id: string): string {
  return id.length > 8 ? id.slice(0, 8) : id;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function JobListPage() {
  const navigate = useNavigate();
  const [statusFilter, setStatusFilter] = useState<JobStatus | "ALL">("ALL");
  const { jobs, isLoading, error, refetch } = useJobs(
    statusFilter === "ALL" ? undefined : { status: statusFilter },
  );
  const { cancel, isCancelling } = useCancelJob();
  const [cancellingId, setCancellingId] = useState<string | null>(null);

  const handleCancel = useCallback(
    async (jobId: string) => {
      if (
        !window.confirm(
          "Are you sure you want to cancel this job? This cannot be undone.",
        )
      ) {
        return;
      }
      setCancellingId(jobId);
      try {
        await cancel(jobId);
        refetch();
      } catch {
        // Error displayed via hook
      } finally {
        setCancellingId(null);
      }
    },
    [cancel, refetch],
  );

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Jobs</h1>
          <p className="mt-1 text-sm text-gray-500">
            Submit and monitor your compute jobs.
          </p>
        </div>
        <Link
          to="/jobs/new"
          className="rounded-md bg-brand-600 px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-brand-700 focus:outline-none focus:ring-2 focus:ring-brand-500 focus:ring-offset-2"
        >
          New Job
        </Link>
      </div>

      {/* Filter bar */}
      <div className="flex items-center gap-2">
        {STATUS_FILTERS.map((sf) => (
          <button
            key={sf.value}
            type="button"
            onClick={() => setStatusFilter(sf.value)}
            className={[
              "rounded-md px-3 py-1.5 text-xs font-medium transition-colors",
              statusFilter === sf.value
                ? "bg-brand-100 text-brand-700"
                : "bg-gray-100 text-gray-600 hover:bg-gray-200",
            ].join(" ")}
          >
            {sf.label}
          </button>
        ))}
        <button
          type="button"
          onClick={refetch}
          className="ml-auto rounded-md border border-gray-300 bg-white px-3 py-1.5 text-xs font-medium text-gray-600 hover:bg-gray-50"
          title="Refresh"
        >
          Refresh
        </button>
      </div>

      {/* Error */}
      {error && (
        <div className="rounded-md bg-red-50 p-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {/* Loading state */}
      {isLoading && (
        <div className="flex justify-center py-12">
          <div className="h-8 w-8 animate-spin rounded-full border-4 border-brand-200 border-t-brand-600" />
        </div>
      )}

      {/* Empty state */}
      {!isLoading && jobs.length === 0 && !error && (
        <div className="rounded-lg border border-dashed border-gray-300 bg-white p-12 text-center">
          <svg
            className="mx-auto h-10 w-10 text-gray-300"
            fill="none"
            viewBox="0 0 24 24"
            strokeWidth={1.5}
            stroke="currentColor"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M20.25 14.15v4.25c0 1.094-.787 2.036-1.872 2.18-2.087.277-4.216.42-6.378.42s-4.291-.143-6.378-.42c-1.085-.144-1.872-1.086-1.872-2.18v-4.25m16.5 0a2.18 2.18 0 00.75-1.661V8.706c0-1.081-.768-2.015-1.837-2.175a48.114 48.114 0 00-3.413-.387m4.5 8.006c-.194.165-.42.295-.673.38A23.978 23.978 0 0112 15.75c-2.648 0-5.195-.429-7.577-1.22a2.016 2.016 0 01-.673-.38m0 0A2.18 2.18 0 013 12.489V8.706c0-1.081.768-2.015 1.837-2.175a48.111 48.111 0 013.413-.387m7.5 0V5.25A2.25 2.25 0 0013.5 3h-3a2.25 2.25 0 00-2.25 2.25v.894m7.5 0a48.667 48.667 0 00-7.5 0"
            />
          </svg>
          <p className="mt-3 text-sm text-gray-500">No jobs found.</p>
          <Link
            to="/jobs/new"
            className="mt-4 inline-block rounded-md bg-brand-600 px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-brand-700"
          >
            Submit Your First Job
          </Link>
        </div>
      )}

      {/* Job table */}
      {!isLoading && jobs.length > 0 && (
        <div className="overflow-hidden rounded-lg border border-gray-200 bg-white shadow-sm">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
                  ID
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
                  Type
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
                  Status
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
                  Created
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
                  Updated
                </th>
                <th className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">
                  Actions
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200">
              {jobs.map((job) => (
                <tr
                  key={job.id}
                  className="cursor-pointer transition-colors hover:bg-gray-50"
                  onClick={() => navigate(`/jobs/${job.id}`)}
                >
                  <td className="whitespace-nowrap px-4 py-3 text-sm font-mono text-gray-900">
                    {shortId(job.id)}
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-700">
                    {job.job_type}
                  </td>
                  <td className="whitespace-nowrap px-4 py-3">
                    <span className={statusBadgeClasses(job.status)}>
                      {statusLabel(job.status)}
                    </span>
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-500">
                    {formatTimestamp(job.created_at)}
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-500">
                    {formatTimestamp(job.updated_at)}
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 text-right">
                    {isJobCancellable(job.status) && (
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          void handleCancel(job.id);
                        }}
                        disabled={isCancelling && cancellingId === job.id}
                        className="rounded-md border border-red-200 bg-white px-2.5 py-1 text-xs font-medium text-red-600 transition-colors hover:bg-red-50 disabled:cursor-not-allowed disabled:opacity-50"
                      >
                        {isCancelling && cancellingId === job.id
                          ? "Cancelling..."
                          : "Cancel"}
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
