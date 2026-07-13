import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";
import { Badge, Button } from "@cloudflare/kumo";
import { CheckCircleIcon, WarningCircleIcon, XCircleIcon, XIcon } from "@phosphor-icons/react";

import type { AuthUser } from "./api";

export type OperatorRole = "viewer" | "operator" | "analyst" | "detector" | "model-risk" | "admin";

export interface ActorPayload {
  actor: string;
  role: OperatorRole;
  source: "console";
  request_id: string;
  reason?: string;
}

type Operation =
  | "database.provision"
  | "model.load"
  | "model.upload"
  | "model.promote"
  | "model.rollback"
  | "healing.approve"
  | "healing.reject"
  | "healing.rollback"
  | "drift.acknowledge"
  | "drift.escalate"
  | "workload.activate";

const MUTATION_PERMISSIONS: Record<Operation, OperatorRole[]> = {
  "database.provision": ["model-risk", "admin"],
  "model.load": ["model-risk", "admin"],
  "model.upload": ["model-risk", "admin"],
  "model.promote": ["model-risk", "admin"],
  "model.rollback": ["model-risk", "admin"],
  "healing.approve": ["model-risk", "admin"],
  "healing.reject": ["model-risk", "admin"],
  "healing.rollback": ["model-risk", "admin"],
  "drift.acknowledge": ["operator", "model-risk", "admin"],
  "drift.escalate": ["operator", "model-risk", "admin"],
  "workload.activate": ["model-risk", "admin"],
};

interface OperatorState {
  actor: string;
  displayName: string;
  role: OperatorRole;
  setActor: (actor: string) => void;
  setRole: (role: OperatorRole) => void;
  logout?: () => Promise<void>;
  can: (operation: Operation) => boolean;
  payload: (reason?: string) => ActorPayload;
}

const OperatorContext = createContext<OperatorState | null>(null);

function requestId(): string {
  return `console-${Date.now()}-${Math.random().toString(16).slice(2, 8)}`;
}

export function OperatorProvider({
  user,
  onLogout,
  children,
}: {
  user: AuthUser;
  onLogout?: () => Promise<void>;
  children: ReactNode;
}) {
  const actor = user.email;
  const role = isOperatorRole(user.role) ? user.role : "viewer";
  const displayName = user.display_name || user.email;
  const setActor = useCallback(() => undefined, []);
  const setRole = useCallback(() => undefined, []);

  const value = useMemo<OperatorState>(
    () => ({
      actor,
      displayName,
      role,
      setActor,
      setRole,
      logout: onLogout,
      can: (operation) => MUTATION_PERMISSIONS[operation].includes(role),
      payload: (reason) => ({
        actor,
        role,
        source: "console",
        request_id: requestId(),
        ...(reason?.trim() ? { reason: reason.trim() } : {}),
      }),
    }),
    [actor, displayName, onLogout, role, setActor, setRole],
  );

  return <OperatorContext.Provider value={value}>{children}</OperatorContext.Provider>;
}

export function useOperator(): OperatorState {
  const value = useContext(OperatorContext);
  if (!value) throw new Error("useOperator must be used inside OperatorProvider");
  return value;
}

export function isOperatorRole(value: string): value is OperatorRole {
  return ["viewer", "operator", "analyst", "detector", "model-risk", "admin"].includes(value);
}

type ToastTone = "success" | "error" | "warning";

interface Toast {
  id: number;
  tone: ToastTone;
  title: string;
  detail?: string;
}

interface ToastState {
  notify: (toast: Omit<Toast, "id">) => void;
}

const ToastContext = createContext<ToastState | null>(null);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const remove = useCallback((id: number) => {
    setToasts((items) => items.filter((item) => item.id !== id));
  }, []);

  const notify = useCallback(
    (toast: Omit<Toast, "id">) => {
      const id = Date.now() + Math.floor(Math.random() * 1000);
      setToasts((items) => [...items.slice(-3), { ...toast, id }]);
      window.setTimeout(() => remove(id), toast.tone === "error" ? 6500 : 4200);
    },
    [remove],
  );

  return (
    <ToastContext.Provider value={{ notify }}>
      {children}
      {createPortal(
        <div className="toast-stack" role="status" aria-live="polite">
          {toasts.map((toast) => (
            <div className={`toast toast-${toast.tone}`} key={toast.id}>
              <div className="toast-icon" aria-hidden="true">
                {toast.tone === "success" ? (
                  <CheckCircleIcon size={18} weight="fill" />
                ) : toast.tone === "warning" ? (
                  <WarningCircleIcon size={18} weight="fill" />
                ) : (
                  <XCircleIcon size={18} weight="fill" />
                )}
              </div>
              <div className="toast-copy">
                <strong>{toast.title}</strong>
                {toast.detail && <span>{toast.detail}</span>}
              </div>
              <Button variant="ghost" shape="square" size="xs" aria-label="Dismiss" onClick={() => remove(toast.id)}>
                <XIcon size={14} />
              </Button>
            </div>
          ))}
        </div>,
        document.body,
      )}
    </ToastContext.Provider>
  );
}

export function useToast(): ToastState {
  const value = useContext(ToastContext);
  if (!value) throw new Error("useToast must be used inside ToastProvider");
  return value;
}

interface ConfirmActionDialogProps {
  open: boolean;
  title: string;
  description: string;
  blastRadius: ReactNode;
  confirmText?: string;
  confirmLabel?: string;
  submitLabel: string;
  busy?: boolean;
  tone?: "danger" | "warning";
  onCancel: () => void;
  onConfirm: (reason: string) => Promise<void>;
}

export function ConfirmActionDialog({
  open,
  title,
  description,
  blastRadius,
  confirmText,
  confirmLabel = "Type to confirm",
  submitLabel,
  busy = false,
  tone = "warning",
  onCancel,
  onConfirm,
}: ConfirmActionDialogProps) {
  const operator = useOperator();
  const [reason, setReason] = useState("");
  const [typed, setTyped] = useState("");
  const [error, setError] = useState<string | null>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const reasonRef = useRef<HTMLTextAreaElement>(null);
  const confirmRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!open) return;
    setReason("");
    setTyped("");
    setError(null);
    window.setTimeout(() => (confirmText ? confirmRef.current : reasonRef.current)?.focus(), 20);
  }, [confirmText, open]);

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onCancel();
        return;
      }
      if (event.key !== "Tab" || !panelRef.current) return;
      const focusable = Array.from(
        panelRef.current.querySelectorAll<HTMLElement>(
          "a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex='-1'])",
        ),
      );
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onCancel, open]);

  if (!open) return null;

  const reasonValid = reason.trim().length >= 8;
  const typedValid = !confirmText || typed.trim() === confirmText;
  const disabled = busy || !reasonValid || !typedValid;

  const submit = async () => {
    if (!reasonValid) {
      setError("Add a justification note with enough detail for review.");
      return;
    }
    if (!typedValid) {
      setError(`Type "${confirmText}" to confirm.`);
      return;
    }
    setError(null);
    await onConfirm(reason.trim());
  };

  return createPortal(
    <div className="modal-overlay" onMouseDown={(event) => event.target === event.currentTarget && onCancel()}>
      <div
        className={`modal-panel confirm-dialog tone-${tone}`}
        role="dialog"
        aria-modal="true"
        aria-labelledby="confirm-title"
        ref={panelRef}
      >
        <div className="confirm-head">
          <div>
            <p className="eyebrow">Production change</p>
            <h2 id="confirm-title">{title}</h2>
          </div>
          <Button aria-label="Close" variant="ghost" shape="square" size="sm" onClick={onCancel}>
            <XIcon size={16} />
          </Button>
        </div>

        <p className="confirm-description">{description}</p>

        <div className="blast-radius">
          <span>Blast radius</span>
          <strong>{blastRadius}</strong>
        </div>

        <div className="confirm-identity">
          <span>Actor</span>
          <Badge variant={operator.role === "admin" || operator.role === "model-risk" ? "purple" : "neutral"}>
            {operator.actor} / {operator.role}
          </Badge>
        </div>

        {confirmText && (
          <label className="confirm-field">
            <span>{confirmLabel}</span>
            <input
              ref={confirmRef}
              value={typed}
              onChange={(event) => setTyped(event.target.value)}
              placeholder={confirmText}
              autoComplete="off"
            />
          </label>
        )}

        <label className="confirm-field">
          <span>Justification note</span>
          <textarea
            ref={reasonRef}
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            rows={4}
            placeholder="Explain why this change is safe and what will be monitored."
          />
        </label>

        {error && <div className="confirm-error">{error}</div>}

        <div className="confirm-actions">
          <Button variant="secondary" onClick={onCancel} disabled={busy}>
            Cancel
          </Button>
          <Button variant={tone === "danger" ? "destructive" : "primary"} onClick={submit} disabled={disabled} loading={busy}>
            {submitLabel}
          </Button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
