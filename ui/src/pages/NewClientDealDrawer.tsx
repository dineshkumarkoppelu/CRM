import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";

import { errorMessage } from "../api/client";
import { useCreateClientWithDeal, useCreateDomain, useDomains, useHealth, useOverride, usePipeline } from "../api/hooks";
import type { AssignmentResult, ClientCreateResult, ClientSize, Domain, DomainInfo, Region } from "../api/types";
import { AssignmentPanel } from "../components/AssignmentPanel";
import { DomainChip } from "../components/Badges";
import { Drawer } from "../components/Overlay";
import { formatINR, SIZE_LABEL } from "../lib/format";

const INDUSTRIES = ["BFSI", "Healthcare", "Retail", "Manufacturing", "Logistics", "EdTech", "Media", "Energy"];
const SIZES: ClientSize[] = ["SMB", "MID_MARKET", "ENTERPRISE"];
const REGIONS: Region[] = ["North", "South", "East", "West", "International"];
const NEW_DOMAIN = "__new__"; // select value for "+ New domain"

interface FormState {
  name: string;
  industry: string;
  size: ClientSize;
  region: Region;
  title: string;
  value: string;
  domain: Domain; // or NEW_DOMAIN
  newDomainName: string;
  newDomainDescription: string;
  expectedClose: string;
  ownerId: string; // "" = assign automatically
}

/** Last day of the month after `asOf` ("YYYY-MM-DD"), a sensible default close date. */
function defaultCloseDate(asOf: string | undefined): string {
  if (!asOf) return "";
  const [y, m] = asOf.split("-").map(Number);
  const last = new Date(Date.UTC(y, m + 1, 0)); // day 0 of month m+2 = last day of month m+1
  return last.toISOString().slice(0, 10);
}

export function NewClientDealDrawer({ open, onClose }: { open: boolean; onClose: () => void }) {
  return (
    <Drawer
      open={open}
      onClose={onClose}
      title="New client and deal"
      subtitle="The deal is assigned automatically unless you choose an owner."
      width={760}
    >
      <NewClientDealForm onClose={onClose} />
    </Drawer>
  );
}

function NewClientDealForm({ onClose }: { onClose: () => void }) {
  const health = useHealth();
  const pipeline = usePipeline();
  const create = useCreateClientWithDeal();
  const createDomain = useCreateDomain();
  const domains = useDomains();
  const override = useOverride();

  const blank = (): FormState => ({
    name: "",
    industry: "Manufacturing",
    size: "MID_MARKET",
    region: "South",
    title: "",
    value: "",
    domain: "IoT",
    newDomainName: "",
    newDomainDescription: "",
    expectedClose: defaultCloseDate(health.data?.as_of_date),
    ownerId: "",
  });
  const [form, setForm] = useState<FormState>(blank);
  const [created, setCreated] = useState<ClientCreateResult | null>(null);
  const [assignment, setAssignment] = useState<AssignmentResult | null>(null);
  const [addedDomain, setAddedDomain] = useState<DomainInfo | null>(null);
  const addingDomain = form.domain === NEW_DOMAIN;

  const set = <K extends keyof FormState>(key: K, value: FormState[K]) => setForm((f) => ({ ...f, [key]: value }));
  const value = Number(form.value);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    let domain = form.domain;
    if (addingDomain) {
      // 1. Add the domain: embedded and linked to the most similar existing domains.
      let added: DomainInfo;
      try {
        added = await createDomain.mutateAsync({
          name: form.newDomainName.trim(),
          description: form.newDomainDescription.trim(),
        });
      } catch {
        return; // error shown below the form
      }
      setAddedDomain(added);
      domain = added.name;
      setForm((f) => ({ ...f, domain: added.name })); // a retry must not add it again
    }
    // 2. Create the client and deal; the engine assigns it.
    create.mutate(
      {
        client: { name: form.name.trim(), industry: form.industry, size: form.size, region: form.region },
        deal: {
          title: form.title.trim(),
          value,
          domain,
          expected_close_date: form.expectedClose,
          owner_id: form.ownerId || null,
        },
      },
      {
        onSuccess: (result) => {
          setCreated(result);
          setAssignment(result.assignment);
        },
      },
    );
  };

  const doOverride = (repId: string) => {
    if (!created) return;
    override.mutate({ dealId: created.deal.id, repId }, { onSuccess: setAssignment });
  };

  if (created && assignment) {
    return (
      <div className="space-y-5 px-5 py-4">
        <div className="flex items-start justify-between gap-4 rounded border border-line bg-canvas/60 px-3.5 py-3">
          <div className="text-[13px]">
            <div className="font-semibold">{created.client.name}</div>
            <div className="mt-0.5 flex flex-wrap items-center gap-2 text-ink-muted">
              <span>{created.deal.title}</span>
              <span>·</span>
              <span className="num">{formatINR(created.deal.value)}</span>
              <DomainChip domain={created.deal.domain} />
            </div>
          </div>
          <span className="text-xs text-won">Created</span>
        </div>

        {addedDomain && addedDomain.name === created.deal.domain && <NewDomainNote domain={addedDomain} />}

        <AssignmentPanel
          result={assignment}
          onOverride={doOverride}
          overridingId={override.isPending ? override.variables?.repId : null}
        />
        {override.error && <p className="text-[13px] text-lost">{errorMessage(override.error)}</p>}

        <div className="flex justify-end gap-2 border-t border-line pt-4">
          <button
            type="button"
            className="btn"
            onClick={() => {
              setCreated(null);
              setAssignment(null);
              setAddedDomain(null);
              setForm(blank());
              create.reset();
              createDomain.reset();
              override.reset();
            }}
          >
            Create another
          </button>
          <Link to={`/deals/${created.deal.id}`} className="btn btn-primary" onClick={onClose}>
            Open deal
          </Link>
        </div>
      </div>
    );
  }

  const owners = [...(pipeline.data?.reps ?? [])].sort((a, b) => a.name.localeCompare(b.name));
  return (
    <form onSubmit={submit} className="space-y-6 px-5 py-4">
      <fieldset className="space-y-3">
        <legend className="section-title mb-2">Client</legend>
        <div>
          <label className="label" htmlFor="client-name">
            Company name
          </label>
          <input id="client-name" className="input" required maxLength={200} value={form.name} onChange={(e) => set("name", e.target.value)} />
        </div>
        <div className="grid grid-cols-3 gap-3">
          <div>
            <label className="label" htmlFor="industry">
              Industry
            </label>
            <select id="industry" className="input" value={form.industry} onChange={(e) => set("industry", e.target.value)}>
              {INDUSTRIES.map((i) => (
                <option key={i}>{i}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="label" htmlFor="size">
              Size
            </label>
            <select id="size" className="input" value={form.size} onChange={(e) => set("size", e.target.value as ClientSize)}>
              {SIZES.map((s) => (
                <option key={s} value={s}>
                  {SIZE_LABEL[s]}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="label" htmlFor="region">
              Region
            </label>
            <select id="region" className="input" value={form.region} onChange={(e) => set("region", e.target.value as Region)}>
              {REGIONS.map((r) => (
                <option key={r}>{r}</option>
              ))}
            </select>
          </div>
        </div>
      </fieldset>

      <fieldset className="space-y-3">
        <legend className="section-title mb-2">First deal</legend>
        <div>
          <label className="label" htmlFor="title">
            Title
          </label>
          <input id="title" className="input" required maxLength={200} value={form.title} onChange={(e) => set("title", e.target.value)} />
        </div>
        <div className="grid grid-cols-3 gap-3">
          <div>
            <label className="label" htmlFor="domain">
              Domain
            </label>
            <select id="domain" className="input" value={form.domain} onChange={(e) => set("domain", e.target.value)}>
              {domains.data?.map((d) => (
                <option key={d}>{d}</option>
              ))}
              <option value={NEW_DOMAIN}>+ New domain…</option>
            </select>
          </div>
          <div>
            <label className="label" htmlFor="value">
              Value (₹)
            </label>
            <input
              id="value"
              className="input num"
              required
              type="number"
              min={1}
              step={1000}
              value={form.value}
              onChange={(e) => set("value", e.target.value)}
            />
            <p className="mt-1 text-xs text-ink-faint">{value > 0 ? formatINR(value) : "Amount in rupees"}</p>
          </div>
          <div>
            <label className="label" htmlFor="close">
              Expected close
            </label>
            <input id="close" className="input" required type="date" value={form.expectedClose} onChange={(e) => set("expectedClose", e.target.value)} />
          </div>
        </div>
        {addingDomain && (
          <div className="space-y-3 rounded border border-accent/25 bg-accent-soft/40 px-3.5 py-3">
            <p className="text-xs leading-relaxed text-ink-muted">
              The new domain is compared with the existing ones using text embeddings of its description. Until sales people
              build a track record in it, the deal goes to the rep with the best results in the most similar domains.
            </p>
            <div>
              <label className="label" htmlFor="new-domain-name">
                Domain name
              </label>
              <input
                id="new-domain-name"
                className="input"
                required
                minLength={2}
                maxLength={40}
                placeholder="e.g. Edge Computing"
                value={form.newDomainName}
                onChange={(e) => set("newDomainName", e.target.value)}
              />
            </div>
            <div>
              <label className="label" htmlFor="new-domain-description">
                What it covers
              </label>
              <textarea
                id="new-domain-description"
                className="input h-auto min-h-16 py-1.5"
                required
                minLength={10}
                maxLength={400}
                rows={3}
                placeholder="e.g. Processing data on devices and gateways close to sensors; low-latency analytics at the edge."
                value={form.newDomainDescription}
                onChange={(e) => set("newDomainDescription", e.target.value)}
              />
              <p className="mt-1 text-xs text-ink-faint">A specific sentence gives a better match than a single word.</p>
            </div>
          </div>
        )}
        <div>
          <label className="label" htmlFor="owner">
            Owner
          </label>
          <select id="owner" className="input" value={form.ownerId} onChange={(e) => set("ownerId", e.target.value)}>
            <option value="">Assign automatically (recommended)</option>
            {owners.map((r) => (
              <option key={r.sales_person_id} value={r.sales_person_id}>
                {r.name} ({r.open_count}/{r.capacity} open)
              </option>
            ))}
          </select>
        </div>
      </fieldset>

      {createDomain.error && (
        <p className="rounded border border-lost/25 bg-lost-soft px-3 py-2 text-[13px] text-lost">
          Could not add the domain: {errorMessage(createDomain.error)}
        </p>
      )}
      {create.error && (
        <p className="rounded border border-lost/25 bg-lost-soft px-3 py-2 text-[13px] text-lost">{errorMessage(create.error)}</p>
      )}

      <div className="flex justify-end gap-2 border-t border-line pt-4">
        <button type="button" className="btn" onClick={onClose}>
          Cancel
        </button>
        <button type="submit" className="btn btn-primary" disabled={create.isPending || createDomain.isPending}>
          {createDomain.isPending ? "Analysing new domain…" : create.isPending ? "Creating…" : "Create and assign"}
        </button>
      </div>
    </form>
  );
}

/** Shown after creating a deal in a domain that was just added. */
function NewDomainNote({ domain }: { domain: DomainInfo }) {
  const used = domain.related.filter((r) => r.used_for_fit);
  return (
    <div className="rounded border border-line bg-panel px-3.5 py-3 text-[13px]">
      <div className="flex items-center gap-2">
        <span className="font-medium">New domain added</span>
        <DomainChip domain={domain.name} />
      </div>
      {used.length > 0 ? (
        <>
          <p className="mt-1.5 text-ink-muted">Closest existing domains by description (used to rank sales people):</p>
          <div className="mt-1.5 flex flex-wrap gap-2">
            {used.map((r) => (
              <span key={r.domain} className="inline-flex items-center gap-1.5">
                <DomainChip domain={r.domain} />
                <span className="num text-xs text-ink-muted">similarity {r.similarity.toFixed(2)}</span>
              </span>
            ))}
          </div>
        </>
      ) : (
        <p className="mt-1.5 text-ink-muted">
          No existing domain is close enough, so the deal was ranked on overall win rate (cold start).
        </p>
      )}
    </div>
  );
}