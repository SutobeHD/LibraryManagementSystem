/**
 * usePhraseBatch — start + poll a phrase-cue batch job.
 *
 * Mirrors the duplicate-finder polling pattern (DuplicateView.jsx):
 * POST /api/phrase/batch/start → job_id, then poll /status every 1.5 s until a
 * terminal status (done|error|cancelled). Exposes the live job dict so the UI
 * can render progress, ETA and per-track skip/fail reasons.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import api from '../api/api';
import toast from 'react-hot-toast';

const POLL_MS = 1500;
const TERMINAL = ['done', 'error', 'cancelled'];

const log = (level, msg, data) => console[level]?.(`[usePhraseBatch] ${msg}`, data ?? '');

export default function usePhraseBatch() {
    const [progress, setProgress] = useState(null); // live job dict from the backend
    const [running, setRunning] = useState(false);
    const [error, setError] = useState(null);
    const pollRef = useRef(null);
    const jobIdRef = useRef(null);

    const stopPoll = useCallback(() => {
        if (pollRef.current) {
            clearInterval(pollRef.current);
            pollRef.current = null;
        }
    }, []);

    const start = useCallback(
        async (payload) => {
            setError(null);
            setProgress(null);
            setRunning(true);

            let jobId = null;
            try {
                const res = await api.post('/api/phrase/batch/start', payload);
                if (res.data?.status !== 'ok') throw new Error(res.data?.message || 'Start failed');
                jobId = res.data.data?.job_id;
                jobIdRef.current = jobId;
                setProgress({
                    status: 'running',
                    total: res.data.data?.total ?? 0,
                    done: 0,
                    succeeded: 0,
                    skipped: 0,
                    failed: 0,
                    percent: 0,
                });
                log('info', 'batch started', { jobId, total: res.data.data?.total });
            } catch (e) {
                const msg = e?.response?.data?.detail || e.message || 'Start failed';
                log('error', 'start failed', e);
                setError(msg);
                setRunning(false);
                toast.error(`Batch start failed: ${msg}`);
                return;
            }

            pollRef.current = setInterval(async () => {
                try {
                    const res = await api.get('/api/phrase/batch/status', {
                        params: { job_id: jobId },
                    });
                    const data = res.data?.data;
                    if (!data) return;
                    setProgress(data);

                    if (TERMINAL.includes(data.status)) {
                        stopPoll();
                        setRunning(false);
                        if (data.status === 'error') {
                            setError(data.error || 'Batch error');
                            toast.error('Batch failed');
                        } else if (data.status === 'cancelled') {
                            toast(`Cancelled — ${data.succeeded} written`);
                        } else {
                            toast.success(
                                `Done: ${data.succeeded} written · ${data.skipped} skipped · ${data.failed} failed`,
                            );
                        }
                    }
                } catch (e) {
                    // Transient poll failure (network blip) — keep polling.
                    log('warn', 'poll error (continuing)', e);
                }
            }, POLL_MS);
        },
        [stopPoll],
    );

    const cancel = useCallback(async () => {
        const jobId = jobIdRef.current;
        if (!jobId) return;
        try {
            await api.post('/api/phrase/batch/cancel', { job_id: jobId });
            log('info', 'cancel requested', { jobId });
        } catch (e) {
            log('error', 'cancel failed', e);
            toast.error('Cancel failed');
        }
    }, []);

    const reset = useCallback(() => {
        stopPoll();
        setProgress(null);
        setRunning(false);
        setError(null);
        jobIdRef.current = null;
    }, [stopPoll]);

    useEffect(() => () => stopPoll(), [stopPoll]);

    return { progress, running, error, start, cancel, reset };
}
