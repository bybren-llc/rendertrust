// MIT License -- see LICENSE-MIT
//
// Job detail page -- shows full job info, status timeline, download result,
// cancel button, and error display with retry option.

import { useCallback, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  useJob,
  useCancelJob,
  useDownloadResult,
  useSubmitJob,
} from "../../hooks/useJobs";
import type { JobStatus } from "../../lib/jobs";
import {
  isJobCancellable,
  statusBadgeClasses,
  statusLabel,
} from "../../lib/jobs";

// ---------------------------------------------------------------------------
// Status timeline steps
// ---------------------------------------------------------------------------

const TIMELINE_STEPS: { status: JobStatus; label: string }[] = [
  { status: "QUEUED", label: "Queued" },
  { status: "DISPATCHED", label: "Dispatched" },
  { status: "RUNNING", label: "Running" },
  { status: "COMPLETED", label: "Completed" },
];

function getStepState(
  stepStatus: JobStatus,
  currentStatus: JobStatus,
): "completed" | "current" | "upcoming" | "failed" {
  if (currentStatus === "FAILED") {
    // Show all steps up to the current position as completed, the next as failed
    const stepIdx = TIMELINE_STEPS.findIndex((s) => s.status === stepStatus);
    const currentIdx = getProgressIndex(currentStatus);
    if (stepIdx < currentIdx) return "completed";
    if (stepIdx === currentIdx) return "failed";
    return "upcoming";
  }

  const stepIdx = TIMELINE_STEPS.findIndex((s) => s.status === stepStatus);
  const currentIdx = TIMELINE_STEPS.findIndex(
    (s) => s.status === currentStatus,
  );

  if (stepIdx < currentIdx) return "completed";
  if (stepIdx === currentIdx) return "current";
  return "upcoming";
}

/** Get the progress index for the current status (for failed jobs). */
function getProgressIndex(status: JobStatus): number {
  // For FAILED, the step index depends on which transition it reached
  const indexMap: Record<string, number> = {
    QUEUED: 0,
    DISPATCHED: 1,
    RUNNING: 2,
    COMPLETED: 3,
    FAILED: 2, // Failed jobs typically fail during or after dispatch/run
  };
  return indexMap[status] ?? 0;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatTimestamp(iso: string | null | undefined): string {
  if (!iso) return "--";
  try {
    const d = new Date(iso);
    return d.toLocaleString(undefined, {
      year: "numeric",
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  } catch {
    return iso;
  }
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function JobDetailPage() {
  const { id: jobId } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { job, isLoading, error } = useJob(jobId);
  const { cancel, isCancelling } = useCancelJob();
  const { download, isDownloading, error: downloadError } =
    useDownloadResult();
  const { submit: retrySubmit, isSubmitting: isRetrying } = useSubmitJob();
  const [actionError, setActionError] = useState<string | null>(null);

  const handleCancel = useCallback(async () => {
    if (
      !jobId ||
      !window.confirm(
        "Are you sure you want to cancel this job? This cannot be undone.",
      )
    ) {
      return;
    }
    setActionError(null);
    try {
      await cancel(jobId);
    } catch (err: unknown) {
      const apiErr = err as { detail?: string };
      setActionError(apiErr.detail || "Failed to cancel job");
    }
  }, [cancel, jobId]);

  const handleDownload = useCallback(async () => {
    if (!jobId) return;
    setActionError(null);
    await download(jobId);
  }, [download, jobId]);

  const handleRetry = useCallback(async () => {
    if (!job) return;
    setActionError(null);
    try {
      const result = await retrySubmit({
        job_type: job.job_type,
        payload_ref: job.payload_ref,
      });
      navigate(`/jobs/${result.job_id}`);
    } catch (err: unknown) {
      const apiErr = err as { detail?: string };
      setActionError(apiErr.detail || "Failed to retry job");
    }
  }, [job, retrySubmit, navigate]);

  // -----------------------------------------------------------------------
  // Loading state
  // -----------------------------------------------------------------------

  if (isLoading) {
    return (
      <div className="flex justify-center py-12">
        <div className="h-8 w-8 animate-spin rounded-full border-4 border-brand-200 border-t-brand-600" />
      </div>
    );
  }

  // -----------------------------------------------------------------------
  // Error state
  // -----------------------------------------------------------------------

  if (error || !job) {
    return (
      <div className="space-y-6">
        <div className="flex items-center gap-3">
          <Link
            to="/jobs"
            className="text-sm font-medium text-brand-600 hover:text-brand-500"
          >
            &larr; Back to Jobs
          </Link>
        </div>
        <div className="rounded-md bg-red-50 p-4 text-sm text-red-700">
          {error || "Job not found."}
        </div>
      </div>
    );
  }

  // -----------------------------------------------------------------------
  // Main content
  // -----------------------------------------------------------------------

  const displayError = actionError || downloadError;

  return (
    <div className="space-y-6">
      {/* Breadcrumb + title */}
      <div className="flex items-center justify-between">
        <div>
          <Link
            to="/jobs"
            className="text-sm font-medium text-brand-600 hover:text-brand-500"
          >
            &larr; Back to Jobs
          </Link>
          <h1 className="mt-2 text-2xl font-bold text-gray-900">
            Job Details
          </h1>
          <p className="mt-1 font-mono text-sm text-gray-500">{job.id}</p>
        </div>
        <span className={statusBadgeClasses(job.status)}>
          {statusLabel(job.status)}
        </span>
      </div>

      {/* Action errors */}
      {displayError && (
        <div className="rounded-md bg-red-50 p-3 text-sm text-red-700">
          {displayError}
        </div>
      )}

      {/* Status timeline */}
      <div className="rounded-lg border border-gray-200 bg-white p-6 shadow-sm">
        <h2 className="mb-4 text-sm font-semibold text-gray-700">
          Status Timeline
        </h2>
        <div className="flex items-center gap-0">
          {TIMELINE_STEPS.map((step, idx) => {
            const state = getStepState(step.status, job.status);
            return (
              <div key={step.status} className="flex flex-1 items-center">
                {/* Step circle */}
                <div className="flex flex-col items-center">
                  <div
                    className={[
                      "flex h-8 w-8 items-center justify-center rounded-full text-xs font-bold",
                      state === "completed"
                        ? "bg-green-500 text-white"
                        : state === "current"
                          ? "bg-brand-600 text-white ring-4 ring-brand-100"
                          : state === "failed"
                            ? "bg-red-500 text-white ring-4 ring-red-100"
                            : "bg-gray-200 text-gray-400",
                    ].join(" ")}
                  >
                    {state === "completed" ? (
                      <svg
                        className="h-4 w-4"
                        fill="none"
                        viewBox="0 0 24 24"
                        strokeWidth={3}
                        stroke="currentColor"
                      >
                        <path
                          strokeLinecap="round"
                          strokeLinejoin="round"
                          d="M4.5 12.75l6 6 9-13.5"
                        />
                      </svg>
                    ) : state === "failed" ? (
                      <svg
                        className="h-4 w-4"
                        fill="none"
                        viewBox="0 0 24 24"
                        strokeWidth={3}
                        stroke="currentColor"
                      >
                        <path
                          strokeLinecap="round"
                          strokeLinejoin="round"
                          d="M6 18L18 6M6 6l12 12"
                        />
                      </svg>
                    ) : (
                      idx + 1
                    )}
                  </div>
                  <p
                    className={[
                      "mt-2 text-xs font-medium",
                      state === "completed" || state === "current"
                        ? "text-gray-900"
                        : state === "failed"
                          ? "text-red-600"
                          : "text-gray-400",
                    ].join(" ")}
                  >
                    {step.label}
                  </p>
                </div>

                {/* Connector line (except for last) */}
                {idx < TIMELINE_STEPS.length - 1 && (
                  <div
                    className={[
                      "mx-2 h-0.5 flex-1",
                      state === "completed" ? "bg-green-500" : "bg-gray-200",
                    ].join(" ")}
                  />
                )}
              </div>
            );
          })}
        </div>
      </div>

      {/* Job information */}
      <div className="rounded-lg border border-gray-200 bg-white p-6 shadow-sm">
        <h2 className="mb-4 text-sm font-semibold text-gray-700">
          Job Information
        </h2>
        <dl className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div>
            <dt className="text-xs font-medium uppercase text-gray-400">
              Job ID
            </dt>
            <dd className="mt-1 font-mono text-sm text-gray-900">{job.id}</dd>
          </div>
          <div>
            <dt className="text-xs font-medium uppercase text-gray-400">
              Node ID
            </dt>
            <dd className="mt-1 font-mono text-sm text-gray-900">
              {job.node_id}
            </dd>
          </div>
          <div>
            <dt className="text-xs font-medium uppercase text-gray-400">
              Job Type
            </dt>
            <dd className="mt-1 text-sm text-gray-900">{job.job_type}</dd>
          </div>
          <div>
            <dt className="text-xs font-medium uppercase text-gray-400">
              Status
            </dt>
            <dd className="mt-1">
              <span className={statusBadgeClasses(job.status)}>
                {statusLabel(job.status)}
              </span>
            </dd>
          </div>
          <div>
            <dt className="text-xs font-medium uppercase text-gray-400">
              Retry Count
            </dt>
            <dd className="mt-1 text-sm text-gray-900">{job.retry_count}</dd>
          </div>
          <div>
            <dt className="text-xs font-medium uppercase text-gray-400">
              Payload Reference
            </dt>
            <dd className="mt-1 truncate font-mono text-sm text-gray-900">
              {job.payload_ref}
            </dd>
          </div>
          {job.result_ref && (
            <div className="sm:col-span-2">
              <dt className="text-xs font-medium uppercase text-gray-400">
                Result Reference
              </dt>
              <dd className="mt-1 truncate font-mono text-sm text-gray-900">
                {job.result_ref}
              </dd>
            </div>
          )}
        </dl>
      </div>

      {/* Timestamps */}
      <div className="rounded-lg border border-gray-200 bg-white p-6 shadow-sm">
        <h2 className="mb-4 text-sm font-semibold text-gray-700">
          Timestamps
        </h2>
        <dl className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div>
            <dt className="text-xs font-medium uppercase text-gray-400">
              Created
            </dt>
            <dd className="mt-1 text-sm text-gray-900">
              {formatTimestamp(job.created_at)}
            </dd>
          </div>
          <div>
            <dt className="text-xs font-medium uppercase text-gray-400">
              Queued
            </dt>
            <dd className="mt-1 text-sm text-gray-900">
              {formatTimestamp(job.queued_at)}
            </dd>
          </div>
          <div>
            <dt className="text-xs font-medium uppercase text-gray-400">
              Dispatched
            </dt>
            <dd className="mt-1 text-sm text-gray-900">
              {formatTimestamp(job.dispatched_at)}
            </dd>
          </div>
          <div>
            <dt className="text-xs font-medium uppercase text-gray-400">
              Completed
            </dt>
            <dd className="mt-1 text-sm text-gray-900">
              {formatTimestamp(job.completed_at)}
            </dd>
          </div>
          <div>
            <dt className="text-xs font-medium uppercase text-gray-400">
              Last Updated
            </dt>
            <dd className="mt-1 text-sm text-gray-900">
              {formatTimestamp(job.updated_at)}
            </dd>
          </div>
        </dl>
      </div>

      {/* Error display (FAILED jobs) */}
      {job.status === "FAILED" && job.error_message && (
        <div className="rounded-lg border border-red-200 bg-red-50 p-6">
          <h2 className="mb-2 text-sm font-semibold text-red-800">
            Error Details
          </h2>
          <p className="font-mono text-sm text-red-700">{job.error_message}</p>
        </div>
      )}

      {/* Action buttons */}
      <div className="flex gap-3">
        {/* Download result (COMPLETED) */}
        {job.status === "COMPLETED" && job.result_ref && (
          <button
            type="button"
            onClick={handleDownload}
            disabled={isDownloading}
            className="flex items-center gap-2 rounded-md bg-green-600 px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-green-700 focus:outline-none focus:ring-2 focus:ring-green-500 focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {isDownloading ? (
              <>
                <span className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent" />
                Preparing...
              </>
            ) : (
              <>
                <svg
                  className="h-4 w-4"
                  fill="none"
                  viewBox="0 0 24 24"
                  strokeWidth={2}
                  stroke="currentColor"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5M16.5 12L12 16.5m0 0L7.5 12m4.5 4.5V3"
                  />
                </svg>
                Download Result
              </>
            )}
          </button>
        )}

        {/* Cancel (QUEUED/DISPATCHED) */}
        {isJobCancellable(job.status) && (
          <button
            type="button"
            onClick={handleCancel}
            disabled={isCancelling}
            className="flex items-center gap-2 rounded-md border border-red-300 bg-white px-4 py-2 text-sm font-medium text-red-600 shadow-sm hover:bg-red-50 focus:outline-none focus:ring-2 focus:ring-red-500 focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {isCancelling ? (
              <>
                <span className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-red-500 border-t-transparent" />
                Cancelling...
              </>
            ) : (
              "Cancel Job"
            )}
          </button>
        )}

        {/* Retry (FAILED) */}
        {job.status === "FAILED" && (
          <button
            type="button"
            onClick={handleRetry}
            disabled={isRetrying}
            className="flex items-center gap-2 rounded-md bg-brand-600 px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-brand-700 focus:outline-none focus:ring-2 focus:ring-brand-500 focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {isRetrying ? (
              <>
                <span className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent" />
                Retrying...
              </>
            ) : (
              <>
                <svg
                  className="h-4 w-4"
                  fill="none"
                  viewBox="0 0 24 24"
                  strokeWidth={2}
                  stroke="currentColor"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0l3.181 3.183a8.25 8.25 0 0013.803-3.7M4.031 9.865a8.25 8.25 0 0113.803-3.7l3.181 3.182"
                  />
                </svg>
                Retry Job
              </>
            )}
          </button>
        )}
      </div>
    </div>
  );
}
