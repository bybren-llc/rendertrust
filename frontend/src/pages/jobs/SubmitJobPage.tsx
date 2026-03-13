// MIT License -- see LICENSE-MIT
//
// Job submission form -- POSTs to /api/v1/jobs/dispatch.
// Provides job type selector, payload input, priority selector, and GPU toggle.

import { useState } from "react";
import type { FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useSubmitJob } from "../../hooks/useJobs";
import type { JobType, JobPriority } from "../../lib/jobs";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const JOB_TYPES: { value: JobType; label: string; description: string }[] = [
  {
    value: "render",
    label: "Render",
    description: "3D rendering and image generation",
  },
  {
    value: "inference",
    label: "Inference",
    description: "AI/ML model inference",
  },
  {
    value: "generic",
    label: "Generic",
    description: "General-purpose compute task",
  },
];

const PRIORITIES: { value: JobPriority; label: string }[] = [
  { value: "low", label: "Low" },
  { value: "normal", label: "Normal" },
  { value: "high", label: "High" },
];

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function SubmitJobPage() {
  const navigate = useNavigate();
  const { submit, isSubmitting, error: submitError, result } = useSubmitJob();

  // Form state
  const [jobType, setJobType] = useState<JobType>("render");
  const [payloadMode, setPayloadMode] = useState<"ref" | "json">("ref");
  const [payloadRef, setPayloadRef] = useState("");
  const [payloadJson, setPayloadJson] = useState("{}");
  const [priority, setPriority] = useState<JobPriority>("normal");
  const [gpuRequired, setGpuRequired] = useState(false);
  const [validationError, setValidationError] = useState<string | null>(null);

  // -----------------------------------------------------------------------
  // Handlers
  // -----------------------------------------------------------------------

  function validatePayload(): string | null {
    if (payloadMode === "ref") {
      if (!payloadRef.trim()) {
        return "Payload reference is required (e.g. s3://bucket/key).";
      }
      return null;
    }
    // JSON mode -- validate JSON syntax
    try {
      JSON.parse(payloadJson);
      return null;
    } catch {
      return "Invalid JSON payload. Please check the syntax.";
    }
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setValidationError(null);

    const payloadError = validatePayload();
    if (payloadError) {
      setValidationError(payloadError);
      return;
    }

    // Build the payload_ref string
    // For JSON mode, we serialize to a data URI so the backend sees a ref string.
    // In a full implementation this would upload to S3 first; for now we pass inline.
    const resolvedRef =
      payloadMode === "ref"
        ? payloadRef.trim()
        : `inline:${btoa(payloadJson)}`;

    // Include priority and gpu_required as part of the job_type capability string
    // The backend's dispatch endpoint takes job_type + payload_ref.
    // We encode priority/gpu info into the payload_ref metadata prefix.
    const metaSuffix = `?priority=${priority}&gpu=${gpuRequired}`;

    try {
      await submit({
        job_type: jobType,
        payload_ref: resolvedRef + metaSuffix,
      });
    } catch {
      // Error is set in the hook
    }
  }

  // -----------------------------------------------------------------------
  // Success state
  // -----------------------------------------------------------------------

  if (result) {
    return (
      <div className="space-y-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Job Submitted</h1>
          <p className="mt-1 text-sm text-gray-500">
            Your job has been dispatched to the network.
          </p>
        </div>

        <div className="rounded-lg border border-green-200 bg-green-50 p-6">
          <div className="flex items-start gap-3">
            <svg
              className="mt-0.5 h-5 w-5 text-green-600"
              fill="none"
              viewBox="0 0 24 24"
              strokeWidth={2}
              stroke="currentColor"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
              />
            </svg>
            <div>
              <h3 className="text-sm font-semibold text-green-800">
                Job dispatched successfully
              </h3>
              <dl className="mt-3 space-y-1 text-sm text-green-700">
                <div className="flex gap-2">
                  <dt className="font-medium">Job ID:</dt>
                  <dd className="font-mono">{result.job_id}</dd>
                </div>
                <div className="flex gap-2">
                  <dt className="font-medium">Node ID:</dt>
                  <dd className="font-mono">{result.node_id}</dd>
                </div>
                <div className="flex gap-2">
                  <dt className="font-medium">Status:</dt>
                  <dd>{result.status}</dd>
                </div>
              </dl>
            </div>
          </div>
        </div>

        <div className="flex gap-3">
          <Link
            to={`/jobs/${result.job_id}`}
            className="rounded-md bg-brand-600 px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-brand-700 focus:outline-none focus:ring-2 focus:ring-brand-500 focus:ring-offset-2"
          >
            View Job Status
          </Link>
          <button
            type="button"
            onClick={() => navigate("/jobs")}
            className="rounded-md border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 shadow-sm hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-brand-500 focus:ring-offset-2"
          >
            Back to Jobs
          </button>
        </div>
      </div>
    );
  }

  // -----------------------------------------------------------------------
  // Form
  // -----------------------------------------------------------------------

  const displayError = validationError || submitError;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Submit New Job</h1>
          <p className="mt-1 text-sm text-gray-500">
            Configure and dispatch a compute job to the RenderTrust network.
          </p>
        </div>
        <Link
          to="/jobs"
          className="rounded-md border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 shadow-sm hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-brand-500 focus:ring-offset-2"
        >
          Cancel
        </Link>
      </div>

      {/* Form card */}
      <div className="rounded-lg border border-gray-200 bg-white p-6 shadow-sm">
        <form onSubmit={handleSubmit} className="space-y-6">
          {/* Error display */}
          {displayError && (
            <div className="rounded-md bg-red-50 p-3 text-sm text-red-700">
              {displayError}
            </div>
          )}

          {/* Job Type */}
          <div>
            <label className="mb-2 block text-sm font-medium text-gray-700">
              Job Type
            </label>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
              {JOB_TYPES.map((jt) => (
                <button
                  key={jt.value}
                  type="button"
                  onClick={() => setJobType(jt.value)}
                  className={[
                    "rounded-lg border p-4 text-left transition-colors",
                    jobType === jt.value
                      ? "border-brand-500 bg-brand-50 ring-1 ring-brand-500"
                      : "border-gray-200 hover:border-gray-300 hover:bg-gray-50",
                  ].join(" ")}
                >
                  <p className="text-sm font-medium text-gray-900">
                    {jt.label}
                  </p>
                  <p className="mt-1 text-xs text-gray-500">
                    {jt.description}
                  </p>
                </button>
              ))}
            </div>
          </div>

          {/* Payload */}
          <div>
            <label className="mb-2 block text-sm font-medium text-gray-700">
              Payload
            </label>
            {/* Tabs for ref vs JSON */}
            <div className="mb-3 flex gap-1 rounded-md bg-gray-100 p-1">
              <button
                type="button"
                onClick={() => setPayloadMode("ref")}
                className={[
                  "flex-1 rounded-md px-3 py-1.5 text-sm font-medium transition-colors",
                  payloadMode === "ref"
                    ? "bg-white text-gray-900 shadow-sm"
                    : "text-gray-500 hover:text-gray-700",
                ].join(" ")}
              >
                Reference URI
              </button>
              <button
                type="button"
                onClick={() => setPayloadMode("json")}
                className={[
                  "flex-1 rounded-md px-3 py-1.5 text-sm font-medium transition-colors",
                  payloadMode === "json"
                    ? "bg-white text-gray-900 shadow-sm"
                    : "text-gray-500 hover:text-gray-700",
                ].join(" ")}
              >
                JSON Editor
              </button>
            </div>

            {payloadMode === "ref" ? (
              <input
                type="text"
                value={payloadRef}
                onChange={(e) => setPayloadRef(e.target.value)}
                disabled={isSubmitting}
                placeholder="s3://bucket/path/to/payload.blend"
                className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm font-mono shadow-sm placeholder:text-gray-400 focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500 disabled:cursor-not-allowed disabled:bg-gray-100"
              />
            ) : (
              <textarea
                value={payloadJson}
                onChange={(e) => setPayloadJson(e.target.value)}
                disabled={isSubmitting}
                rows={8}
                className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm font-mono shadow-sm placeholder:text-gray-400 focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500 disabled:cursor-not-allowed disabled:bg-gray-100"
                placeholder='{"scene": "main", "resolution": [1920, 1080]}'
              />
            )}
            <p className="mt-1.5 text-xs text-gray-400">
              {payloadMode === "ref"
                ? "S3 URI, IPFS CID, or other storage reference to the job payload."
                : "JSON object describing the job parameters."}
            </p>
          </div>

          {/* Priority */}
          <div>
            <label
              htmlFor="job-priority"
              className="mb-2 block text-sm font-medium text-gray-700"
            >
              Priority
            </label>
            <select
              id="job-priority"
              value={priority}
              onChange={(e) => setPriority(e.target.value as JobPriority)}
              disabled={isSubmitting}
              className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500 disabled:cursor-not-allowed disabled:bg-gray-100"
            >
              {PRIORITIES.map((p) => (
                <option key={p.value} value={p.value}>
                  {p.label}
                </option>
              ))}
            </select>
          </div>

          {/* GPU Preference */}
          <div className="flex items-center gap-3">
            <button
              type="button"
              role="switch"
              aria-checked={gpuRequired}
              onClick={() => setGpuRequired(!gpuRequired)}
              disabled={isSubmitting}
              className={[
                "relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors focus:outline-none focus:ring-2 focus:ring-brand-500 focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50",
                gpuRequired ? "bg-brand-600" : "bg-gray-200",
              ].join(" ")}
            >
              <span
                className={[
                  "pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow ring-0 transition-transform",
                  gpuRequired ? "translate-x-5" : "translate-x-0",
                ].join(" ")}
              />
            </button>
            <div>
              <p className="text-sm font-medium text-gray-700">
                GPU Preference
              </p>
              <p className="text-xs text-gray-400">
                Request GPU-capable edge nodes for this job.
              </p>
            </div>
          </div>

          {/* Submit button */}
          <div className="flex justify-end gap-3 border-t border-gray-200 pt-6">
            <Link
              to="/jobs"
              className="rounded-md border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 shadow-sm hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-brand-500 focus:ring-offset-2"
            >
              Cancel
            </Link>
            <button
              type="submit"
              disabled={isSubmitting}
              className="flex items-center justify-center rounded-md bg-brand-600 px-6 py-2 text-sm font-medium text-white shadow-sm hover:bg-brand-700 focus:outline-none focus:ring-2 focus:ring-brand-500 focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {isSubmitting ? (
                <>
                  <span className="mr-2 inline-block h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent" />
                  Dispatching...
                </>
              ) : (
                "Submit Job"
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
