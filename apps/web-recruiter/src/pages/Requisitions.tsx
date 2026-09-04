import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { motion } from "motion/react";
import { Badge, Button, Card, EmptyState, Field, Input, Select, Skeleton } from "@aiva/ui";
import {
  createDepartment,
  createRequisition,
  getMe,
  listDepartments,
  listRequisitions,
  type CurrentUser,
  type Department,
  type RequisitionSummary,
} from "../api/client";

const STATUS_TONE: Record<string, "positive" | "neutral" | "warning"> = {
  open: "positive",
  draft: "neutral",
  closed: "warning",
};

export function RequisitionsPage() {
  const [me, setMe] = useState<CurrentUser | null>(null);
  const [departments, setDepartments] = useState<Department[] | null>(null);
  const [requisitions, setRequisitions] = useState<RequisitionSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [newDeptName, setNewDeptName] = useState("");
  const [deptBusy, setDeptBusy] = useState(false);

  const [newReqTitle, setNewReqTitle] = useState("");
  const [newReqDept, setNewReqDept] = useState("");
  const [reqBusy, setReqBusy] = useState(false);

  useEffect(() => {
    document.title = "AIVA — Requisitions";
  }, []);

  async function refresh(orgId: string) {
    const [deptResponse, reqResponse] = await Promise.all([
      listDepartments(orgId),
      listRequisitions(orgId),
    ]);
    setDepartments(deptResponse.departments);
    setRequisitions(reqResponse.requisitions);
  }

  useEffect(() => {
    let cancelled = false;
    getMe()
      .then(async (user) => {
        if (cancelled) return;
        setMe(user);
        await refresh(user.organization_id);
      })
      .catch((cause: unknown) => {
        if (!cancelled) setError(cause instanceof Error ? cause.message : "Failed to load");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  async function submitDepartment(event: React.FormEvent) {
    event.preventDefault();
    if (!me || !newDeptName.trim()) return;
    setDeptBusy(true);
    setError(null);
    try {
      await createDepartment(me.organization_id, newDeptName.trim());
      setNewDeptName("");
      await refresh(me.organization_id);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Failed to create department");
    } finally {
      setDeptBusy(false);
    }
  }

  async function submitRequisition(event: React.FormEvent) {
    event.preventDefault();
    if (!me || !newReqTitle.trim() || !newReqDept) return;
    setReqBusy(true);
    setError(null);
    try {
      await createRequisition(newReqDept, newReqTitle.trim());
      setNewReqTitle("");
      await refresh(me.organization_id);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Failed to create requisition");
    } finally {
      setReqBusy(false);
    }
  }

  const loading = !departments || !requisitions;

  return (
    <main className="mx-auto max-w-5xl px-6 py-10 text-[var(--mist)]">
      <header className="mb-8">
        <h1 className="display text-2xl font-semibold">Requisitions</h1>
        <p className="mt-1 text-sm text-[var(--haze)]">
          Open a requisition to manage its job description, resumes, questionnaire, and
          interviews.
        </p>
      </header>

      {error ? (
        <Card className="mb-6">
          <p role="alert" className="text-sm text-[var(--danger)]">
            {error}
          </p>
        </Card>
      ) : null}

      <div className="mb-8 grid gap-4 sm:grid-cols-2">
        <Card>
          <h2 className="display mb-4 text-sm font-semibold uppercase tracking-wide text-[var(--haze)]">
            New department
          </h2>
          <form
            onSubmit={(event) => {
              void submitDepartment(event);
            }}
            className="flex flex-col gap-3"
          >
            <Field label="Name" htmlFor="dept-name">
              <Input
                id="dept-name"
                value={newDeptName}
                onChange={(event) => setNewDeptName(event.target.value)}
                placeholder="Engineering"
                required
              />
            </Field>
            <Button type="submit" variant="ghost" disabled={deptBusy}>
              {deptBusy ? "Creating…" : "Create department"}
            </Button>
          </form>
        </Card>

        <Card>
          <h2 className="display mb-4 text-sm font-semibold uppercase tracking-wide text-[var(--haze)]">
            New requisition
          </h2>
          <form
            onSubmit={(event) => {
              void submitRequisition(event);
            }}
            className="flex flex-col gap-3"
          >
            <Field label="Department" htmlFor="req-dept">
              <Select
                id="req-dept"
                value={newReqDept}
                onChange={(event) => setNewReqDept(event.target.value)}
                required
              >
                <option value="">Select a department…</option>
                {departments?.map((dept) => (
                  <option key={dept.id} value={dept.id}>
                    {dept.name}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="Title" htmlFor="req-title">
              <Input
                id="req-title"
                value={newReqTitle}
                onChange={(event) => setNewReqTitle(event.target.value)}
                placeholder="Senior Backend Engineer"
                required
              />
            </Field>
            <Button
              type="submit"
              disabled={reqBusy || departments?.length === 0}
              arrow
            >
              {reqBusy ? "Creating…" : "Create requisition"}
            </Button>
            {departments?.length === 0 ? (
              <p className="text-xs text-[var(--haze)]">Create a department first.</p>
            ) : null}
          </form>
        </Card>
      </div>

      {loading && !error ? (
        <div className="grid gap-3">
          <Skeleton className="h-16 w-full" />
          <Skeleton className="h-16 w-full" />
        </div>
      ) : null}

      {requisitions?.length === 0 ? (
        <EmptyState
          title="No requisitions yet"
          body="Create a department and a requisition above to get started."
        />
      ) : null}

      <ul className="grid gap-3">
        {requisitions?.map((req) => (
          <motion.li key={req.id} layout transition={{ type: "spring", stiffness: 260, damping: 26 }}>
            <Link to={`/requisitions/${req.id}`}>
              <Card interactive className="flex flex-wrap items-center justify-between gap-4 py-4">
                <div>
                  <p className="font-medium">{req.title}</p>
                  <p className="mono mt-1 text-xs text-[var(--haze)]">{req.department_name}</p>
                </div>
                <Badge tone={STATUS_TONE[req.status] ?? "neutral"}>{req.status}</Badge>
              </Card>
            </Link>
          </motion.li>
        ))}
      </ul>
    </main>
  );
}
