import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Badge, Button, Card, EmptyState, Field, Input, Skeleton } from "@aiva/ui";
import { bookSlot, generateSlots, listSlots, type InterviewSlotSummary } from "../api/client";

function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

function inTwoWeeksIso(): string {
  const date = new Date();
  date.setDate(date.getDate() + 14);
  return date.toISOString().slice(0, 10);
}

const STATUS_TONE: Record<string, "positive" | "neutral" | "warning"> = {
  open: "positive",
  booked: "warning",
  cancelled: "neutral",
};

export function SchedulingPage() {
  const { id: routeRequisitionId } = useParams();
  const [slots, setSlots] = useState<InterviewSlotSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [generating, setGenerating] = useState(false);

  const [dateFrom, setDateFrom] = useState(todayIso());
  const [dateTo, setDateTo] = useState(inTwoWeeksIso());
  const [localStart, setLocalStart] = useState("09:00");
  const [localEnd, setLocalEnd] = useState("17:00");
  const [duration, setDuration] = useState(45);
  const [buffer, setBuffer] = useState(10);
  const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone;

  const [bookingSlot, setBookingSlot] = useState<string | null>(null);
  const [bookingEmail, setBookingEmail] = useState("");
  const [bookingBusy, setBookingBusy] = useState(false);
  const [lastIcs, setLastIcs] = useState<string | null>(null);

  useEffect(() => {
    document.title = "AIVA — Scheduling";
  }, []);

  async function refresh(rid: string) {
    const response = await listSlots(rid);
    setSlots(response.slots);
  }

  useEffect(() => {
    if (!routeRequisitionId) return;
    let cancelled = false;
    refresh(routeRequisitionId).catch((cause: unknown) => {
      if (!cancelled) setError(cause instanceof Error ? cause.message : "Failed to load");
    });
    return () => {
      cancelled = true;
    };
  }, [routeRequisitionId]);

  if (!routeRequisitionId) return null;
  const requisitionId = routeRequisitionId;

  async function submitGenerate(event: React.FormEvent) {
    event.preventDefault();
    setGenerating(true);
    setError(null);
    try {
      await generateSlots(requisitionId, {
        date_from: dateFrom,
        date_to: dateTo,
        timezone_name: timezone,
        local_start: `${localStart}:00`,
        local_end: `${localEnd}:00`,
        duration_minutes: duration,
        buffer_minutes: buffer,
        include_weekends: false,
      });
      await refresh(requisitionId);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Failed to generate slots");
    } finally {
      setGenerating(false);
    }
  }

  async function submitBooking(slotId: string) {
    if (!bookingEmail.trim()) return;
    setBookingBusy(true);
    setError(null);
    try {
      const result = await bookSlot(slotId, bookingEmail.trim());
      setLastIcs(result.ics);
      setBookingEmail("");
      setBookingSlot(null);
      await refresh(requisitionId);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Failed to book slot");
    } finally {
      setBookingBusy(false);
    }
  }

  return (
    <main className="mx-auto max-w-4xl px-6 py-10 text-[var(--mist)]">
      <header className="mb-8">
        <Link
          to={`/requisitions/${requisitionId}`}
          className="text-xs text-[var(--haze)] hover:text-[var(--signal-text)]"
        >
          ← Requisition
        </Link>
        <h1 className="display mt-1 text-2xl font-semibold">Scheduling</h1>
        <p className="mt-1 text-sm text-[var(--haze)]">Timezone: {timezone}</p>
      </header>

      {error ? (
        <Card className="mb-6">
          <p role="alert" className="text-sm text-[var(--danger)]">
            {error}
          </p>
        </Card>
      ) : null}

      <Card className="mb-8">
        <h2 className="display mb-4 text-sm font-semibold uppercase tracking-wide text-[var(--haze)]">
          Generate availability
        </h2>
        <form
          onSubmit={(event) => {
            void submitGenerate(event);
          }}
          className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3"
        >
          <Field label="From" htmlFor="date-from">
            <Input
              id="date-from"
              type="date"
              value={dateFrom}
              onChange={(event) => setDateFrom(event.target.value)}
            />
          </Field>
          <Field label="To" htmlFor="date-to">
            <Input
              id="date-to"
              type="date"
              value={dateTo}
              onChange={(event) => setDateTo(event.target.value)}
            />
          </Field>
          <Field label="Duration (min)" htmlFor="duration">
            <Input
              id="duration"
              type="number"
              min={15}
              max={180}
              value={duration}
              onChange={(event) => setDuration(Number(event.target.value))}
            />
          </Field>
          <Field label="Daily start" htmlFor="local-start">
            <Input
              id="local-start"
              type="time"
              value={localStart}
              onChange={(event) => setLocalStart(event.target.value)}
            />
          </Field>
          <Field label="Daily end" htmlFor="local-end">
            <Input
              id="local-end"
              type="time"
              value={localEnd}
              onChange={(event) => setLocalEnd(event.target.value)}
            />
          </Field>
          <Field label="Buffer (min)" htmlFor="buffer">
            <Input
              id="buffer"
              type="number"
              min={0}
              max={60}
              value={buffer}
              onChange={(event) => setBuffer(Number(event.target.value))}
            />
          </Field>
          <Button type="submit" disabled={generating} arrow className="sm:col-span-2 lg:col-span-3">
            {generating ? "Generating…" : "Generate slots"}
          </Button>
        </form>
      </Card>

      {lastIcs ? (
        <Card className="mb-6 border-[var(--signal)]">
          <p className="mb-2 text-sm font-medium">Booking confirmed — calendar invite:</p>
          <pre className="mono max-h-40 overflow-auto whitespace-pre-wrap text-xs text-[var(--haze)]">
            {lastIcs}
          </pre>
        </Card>
      ) : null}

      <h2 className="display mb-4 text-lg font-semibold">Slots</h2>
      {!slots && !error ? <Skeleton className="h-24 w-full" /> : null}
      {slots?.length === 0 ? (
        <EmptyState title="No slots yet" body="Generate availability above." />
      ) : null}
      <ul className="grid gap-3">
        {slots?.map((slot) => (
          <Card key={slot.id}>
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <p className="font-medium">
                  {new Date(slot.start_at).toLocaleString()} –{" "}
                  {new Date(slot.end_at).toLocaleTimeString()}
                </p>
                {slot.booked_for_email ? (
                  <p className="mono mt-1 text-xs text-[var(--haze)]">{slot.booked_for_email}</p>
                ) : null}
              </div>
              <div className="flex items-center gap-3">
                <Badge tone={STATUS_TONE[slot.status] ?? "neutral"}>{slot.status}</Badge>
                {slot.status === "open" ? (
                  <Button
                    variant="ghost"
                    onClick={() => setBookingSlot(bookingSlot === slot.id ? null : slot.id)}
                  >
                    Book
                  </Button>
                ) : null}
              </div>
            </div>
            {bookingSlot === slot.id ? (
              <form
                onSubmit={(event) => {
                  event.preventDefault();
                  void submitBooking(slot.id);
                }}
                className="mt-4 flex flex-wrap items-end gap-3"
              >
                <div className="min-w-64 flex-1">
                  <Field label="Candidate email" htmlFor={`book-${slot.id}`}>
                    <Input
                      id={`book-${slot.id}`}
                      type="email"
                      required
                      value={bookingEmail}
                      onChange={(event) => setBookingEmail(event.target.value)}
                    />
                  </Field>
                </div>
                <Button type="submit" disabled={bookingBusy}>
                  {bookingBusy ? "Booking…" : "Confirm"}
                </Button>
              </form>
            ) : null}
          </Card>
        ))}
      </ul>
    </main>
  );
}
