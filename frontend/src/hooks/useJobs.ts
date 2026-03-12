// MIT License -- see LICENSE-MIT
//
// React hooks for the RenderTrust job system.
// Provides data fetching with polling, job submission, cancellation, and result download.

import { useCallback, useEffect, useRef, useState } from "react";
import type {
  DispatchRequest,
  DispatchResponse,
  Job,
  JobListResponse,
  JobResultResponse,
  JobStatus,
} from "../lib/jobs";
import {
  cancelJob as apiCancelJob,
  fetchJob,
  fetchJobResult,
  fetchJobs,
  isJobActive,
  submitJob as apiSubmitJob,
} from "../lib/jobs";
import type { ApiError } from "../lib/api";

// ---------------------------------------------------------------------------
// Polling interval (ms)
// ---------------------------------------------------------------------------

const POLL_INTERVAL_MS = 5000;

// ---------------------------------------------------------------------------
// useJobs -- paginated job list with auto-refresh polling
// ---------------------------------------------------------------------------

export interface UseJobsResult {
  jobs: Job[];
  count: number;
  isLoading: boolean;
  error: string | null;
  refetch: () => void;
}

export function useJobs(params?: {
  status?: JobStatus;
  limit?: number;
  offset?: number;
}): UseJobsResult {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [count, setCount] = useState(0);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);

  // Stable reference to params to avoid infinite re-renders
  const statusFilter = params?.status;
  const limit = params?.limit;
  const offset = params?.offset;

  const refetch = useCallback(() => {
    setTick((t) => t + 1);
  }, []);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const data: JobListResponse = await fetchJobs({
          status: statusFilter,
          limit,
          offset,
        });
        if (!cancelled) {
          setJobs(data.jobs);
          setCount(data.count);
          setError(null);
        }
      } catch (err: unknown) {
        if (!cancelled) {
          const apiErr = err as ApiError;
          setError(apiErr.detail || "Failed to load jobs");
        }
      } finally {
        if (!cancelled) {
          setIsLoading(false);
        }
      }
    }

    void load();

    return () => {
      cancelled = true;
    };
  }, [statusFilter, limit, offset, tick]);

  // Auto-refresh when any job is in an active state
  useEffect(() => {
    const hasActiveJobs = jobs.some((j) => isJobActive(j.status));
    if (!hasActiveJobs) return;

    const interval = setInterval(() => {
      setTick((t) => t + 1);
    }, POLL_INTERVAL_MS);

    return () => clearInterval(interval);
  }, [jobs]);

  return { jobs, count, isLoading, error, refetch };
}

// ---------------------------------------------------------------------------
// useJob -- single job with auto-refresh polling
// ---------------------------------------------------------------------------

export interface UseJobResult {
  job: Job | null;
  isLoading: boolean;
  error: string | null;
  refetch: () => void;
}

export function useJob(jobId: string | undefined): UseJobResult {
  const [job, setJob] = useState<Job | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);

  const refetch = useCallback(() => {
    setTick((t) => t + 1);
  }, []);

  useEffect(() => {
    if (!jobId) {
      setIsLoading(false);
      return;
    }

    let cancelled = false;

    async function load() {
      try {
        const data = await fetchJob(jobId!);
        if (!cancelled) {
          setJob(data);
          setError(null);
        }
      } catch (err: unknown) {
        if (!cancelled) {
          const apiErr = err as ApiError;
          setError(apiErr.detail || "Failed to load job");
        }
      } finally {
        if (!cancelled) {
          setIsLoading(false);
        }
      }
    }

    void load();

    return () => {
      cancelled = true;
    };
  }, [jobId, tick]);

  // Auto-refresh while job is active
  useEffect(() => {
    if (!job || !isJobActive(job.status)) return;

    const interval = setInterval(() => {
      setTick((t) => t + 1);
    }, POLL_INTERVAL_MS);

    return () => clearInterval(interval);
  }, [job]);

  return { job, isLoading, error, refetch };
}

// ---------------------------------------------------------------------------
// useSubmitJob -- mutation hook for job dispatch
// ---------------------------------------------------------------------------

export interface UseSubmitJobResult {
  submit: (data: DispatchRequest) => Promise<DispatchResponse>;
  isSubmitting: boolean;
  error: string | null;
  result: DispatchResponse | null;
  reset: () => void;
}

export function useSubmitJob(): UseSubmitJobResult {
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<DispatchResponse | null>(null);

  const submit = useCallback(async (data: DispatchRequest) => {
    setIsSubmitting(true);
    setError(null);
    try {
      const response = await apiSubmitJob(data);
      setResult(response);
      return response;
    } catch (err: unknown) {
      const apiErr = err as ApiError;
      const msg = apiErr.detail || "Failed to submit job";
      setError(msg);
      throw err;
    } finally {
      setIsSubmitting(false);
    }
  }, []);

  const reset = useCallback(() => {
    setError(null);
    setResult(null);
  }, []);

  return { submit, isSubmitting, error, result, reset };
}

// ---------------------------------------------------------------------------
// useCancelJob -- mutation hook for job cancellation
// ---------------------------------------------------------------------------

export interface UseCancelJobResult {
  cancel: (jobId: string) => Promise<Job>;
  isCancelling: boolean;
  error: string | null;
}

export function useCancelJob(): UseCancelJobResult {
  const [isCancelling, setIsCancelling] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const cancel = useCallback(async (jobId: string) => {
    setIsCancelling(true);
    setError(null);
    try {
      const job = await apiCancelJob(jobId);
      return job;
    } catch (err: unknown) {
      const apiErr = err as ApiError;
      const msg = apiErr.detail || "Failed to cancel job";
      setError(msg);
      throw err;
    } finally {
      setIsCancelling(false);
    }
  }, []);

  return { cancel, isCancelling, error };
}

// ---------------------------------------------------------------------------
// useDownloadResult -- fetch presigned URL and trigger download
// ---------------------------------------------------------------------------

export interface UseDownloadResultReturn {
  download: (jobId: string) => Promise<void>;
  isDownloading: boolean;
  error: string | null;
}

export function useDownloadResult(): UseDownloadResultReturn {
  const [isDownloading, setIsDownloading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const anchorRef = useRef<HTMLAnchorElement | null>(null);

  const download = useCallback(async (jobId: string) => {
    setIsDownloading(true);
    setError(null);
    try {
      const data: JobResultResponse = await fetchJobResult(jobId);

      // Open the presigned URL in a new tab / trigger download
      if (!anchorRef.current) {
        anchorRef.current = document.createElement("a");
      }
      anchorRef.current.href = data.download_url;
      anchorRef.current.target = "_blank";
      anchorRef.current.rel = "noopener noreferrer";
      anchorRef.current.click();
    } catch (err: unknown) {
      const apiErr = err as ApiError;
      const msg = apiErr.detail || "Failed to download result";
      setError(msg);
    } finally {
      setIsDownloading(false);
    }
  }, []);

  return { download, isDownloading, error };
}
