'use client';

import React, { useState } from 'react';
import { Button } from '@/components/ui/button';

// Healthcare cross icon
function HealthcareIcon() {
  return (
    <svg
      width="64"
      height="64"
      viewBox="0 0 64 64"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className="text-foreground mb-4 size-16"
      aria-hidden="true"
    >
      <circle cx="32" cy="32" r="30" stroke="currentColor" strokeWidth="2" opacity="0.15" />
      <rect x="26" y="14" width="12" height="36" rx="3" fill="currentColor" opacity="0.8" />
      <rect x="14" y="26" width="36" height="12" rx="3" fill="currentColor" opacity="0.8" />
    </svg>
  );
}

// Animated pulsing dots for connecting state
function PulsingDots() {
  return (
    <div className="mt-3 flex items-center justify-center gap-1.5" aria-hidden="true">
      {[0, 1, 2].map((i) => (
        <span
          key={i}
          className="inline-block size-2 rounded-full bg-current opacity-60"
          style={{ animation: `sb-pulse 1.2s ease-in-out ${i * 0.2}s infinite` }}
        />
      ))}
      <style>{`
        @keyframes sb-pulse {
          0%, 80%, 100% { transform: scale(0.6); opacity: 0.35; }
          40% { transform: scale(1); opacity: 1; }
        }
      `}</style>
    </div>
  );
}

// Microphone blocked icon
function MicBlockedIcon() {
  return (
    <svg
      width="56"
      height="56"
      viewBox="0 0 56 56"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className="text-destructive mb-4 size-14"
      aria-hidden="true"
    >
      <circle cx="28" cy="28" r="26" stroke="currentColor" strokeWidth="2" opacity="0.2" />
      <rect x="22" y="12" width="12" height="20" rx="6" fill="currentColor" opacity="0.45" />
      <path
        d="M16 28c0 6.627 5.373 12 12 12s12-5.373 12-12"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        opacity="0.45"
      />
      <line
        x1="28"
        y1="40"
        x2="28"
        y2="46"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        opacity="0.45"
      />
      <line
        x1="23"
        y1="46"
        x2="33"
        y2="46"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        opacity="0.45"
      />
      <line
        x1="11"
        y1="11"
        x2="45"
        y2="45"
        stroke="currentColor"
        strokeWidth="2.5"
        strokeLinecap="round"
      />
    </svg>
  );
}

export type WelcomeState = 'ready' | 'connecting' | 'ended';

interface WelcomeViewProps {
  startButtonText: string;
  onStartCall: () => void;
  /** Current state of the pre-session view */
  viewState?: WelcomeState;
}

export const WelcomeView = ({
  startButtonText,
  onStartCall,
  viewState = 'ready',
  ref,
  ...rest
}: React.ComponentProps<'div'> & WelcomeViewProps) => {
  const [micError, setMicError] = useState(false);
  const [retrying, setRetrying] = useState(false);

  const handleStartCall = async () => {
    setMicError(false);
    // Pre-check microphone permission to give a clear error instead of failing silently
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      // Stop the test stream immediately — the agent will open its own
      stream.getTracks().forEach((t) => t.stop());
    } catch {
      setMicError(true);
      return;
    }
    onStartCall();
  };

  const handleRetry = async () => {
    setRetrying(true);
    setMicError(false);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      stream.getTracks().forEach((t) => t.stop());
      setRetrying(false);
      onStartCall();
    } catch {
      setRetrying(false);
      setMicError(true);
    }
  };

  return (
    <div
      ref={ref}
      className="flex min-h-[calc(100vh-80px)] w-full flex-col items-center justify-center px-4"
      {...rest}
    >
      <section className="bg-background flex max-w-md flex-col items-center justify-center text-center">
        {/* ── MICROPHONE PERMISSION ERROR ──────────────────────────── */}
        {micError && (
          <>
            <MicBlockedIcon />
            <h1 className="text-foreground text-lg font-semibold tracking-tight">
              Microphone Access Required
            </h1>
            <p className="text-muted-foreground mt-2 max-w-xs text-sm leading-relaxed">
              Swasthya Bharat needs microphone access to have a voice conversation with you.
            </p>
            <div className="bg-muted text-muted-foreground mt-4 w-full rounded-lg px-4 py-3 text-left text-xs">
              <p className="mb-1 font-semibold">How to allow microphone access:</p>
              <ol className="list-inside list-decimal space-y-1">
                <li>Click the lock icon in your browser address bar.</li>
                <li>
                  Find <strong>Microphone</strong> and set it to <strong>Allow</strong>.
                </li>
                <li>
                  Click <strong>Try Again</strong> below.
                </li>
              </ol>
            </div>
            <Button
              id="mic-retry-button"
              size="lg"
              onClick={handleRetry}
              disabled={retrying}
              className="mt-5 min-w-[200px] cursor-pointer rounded-full px-8 py-3 font-mono text-xs font-bold tracking-wider uppercase"
            >
              {retrying ? 'Checking…' : 'Try Again'}
            </Button>
          </>
        )}

        {/* ── CONNECTING ───────────────────────────────────────────── */}
        {!micError && viewState === 'connecting' && (
          <>
            <HealthcareIcon />
            <h1 className="text-foreground text-lg font-semibold tracking-tight">
              Connecting to Swasthya Bharat…
            </h1>
            <p className="text-muted-foreground mt-1 text-sm">Please wait while we connect you.</p>
            <PulsingDots />
            <Button
              id="start-call-button"
              size="lg"
              disabled
              className="mt-6 min-w-[280px] cursor-not-allowed rounded-full px-8 py-3 font-mono text-xs font-bold tracking-wider uppercase opacity-50 sm:min-w-[320px]"
            >
              Connecting…
            </Button>
          </>
        )}

        {/* ── CALL ENDED ───────────────────────────────────────────── */}
        {!micError && viewState === 'ended' && (
          <>
            <HealthcareIcon />
            <h1 className="text-foreground text-lg font-semibold tracking-tight">
              Conversation Ended
            </h1>
            <p className="text-muted-foreground mt-2 text-sm">
              Thank you for speaking with Swasthya Bharat.
            </p>
            <Button
              id="start-again-button"
              size="lg"
              onClick={handleStartCall}
              className="mt-6 min-w-[280px] cursor-pointer rounded-full px-8 py-3 font-mono text-xs font-bold tracking-wider uppercase sm:min-w-[320px]"
            >
              Start Again
            </Button>
          </>
        )}

        {/* ── READY (default) ──────────────────────────────────────── */}
        {!micError && viewState === 'ready' && (
          <>
            <HealthcareIcon />
            <h1 className="text-foreground text-lg font-semibold tracking-tight">
              Swasthya Bharat (સ્વાસ્થ્ય ભારત)
            </h1>
            <p className="text-muted-foreground mt-1 text-sm">
              Your AI Health Assistant • ગુજરાતી &amp; English
            </p>
            <p className="text-muted-foreground mt-0.5 text-xs font-medium">Ready to talk</p>

            <Button
              id="start-call-button"
              size="lg"
              onClick={handleStartCall}
              className="mt-6 min-w-[280px] cursor-pointer rounded-full px-8 py-3 font-mono text-xs font-bold tracking-wider uppercase sm:min-w-[320px]"
            >
              {startButtonText}
            </Button>

            <p className="text-muted-foreground mt-4 text-xs leading-5">
              આયુષ્માન PM-JAY કાર્ડ, ABHA હેલ્થ ID, સરકારી હોસ્પિટલ અને સ્વાસ્થ્ય સેવાની માહિતી માટે
              પૂછો
            </p>
          </>
        )}
      </section>

      {/* ── Healthcare Disclaimer & Analytics Link (non-intrusive, fixed bottom) ──── */}
      <div className="fixed bottom-4 left-0 flex w-full flex-col items-center justify-center gap-1 px-4">
        <a
          href="/analytics"
          className="text-xs font-medium text-sky-400 opacity-90 transition hover:underline hover:opacity-100"
        >
          📊 View Call Analytics Dashboard
        </a>
        <p className="text-muted-foreground max-w-prose text-center text-xs leading-5 font-normal">
          <strong>Disclaimer:</strong> Swasthya Bharat provides general health information and does
          not replace professional medical advice.
        </p>
      </div>
    </div>
  );
};
