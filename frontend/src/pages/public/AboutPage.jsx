import { Card, CardBody } from '@/components/ui/Card';
import { Badge } from '@/components/ui/Badge';
import { SectionHeading } from '@/components/common/SectionHeading';

/**
 * About page: context, scope and an honest statement of what this release does
 * and does not do. Being explicit about phase boundaries avoids overclaiming —
 * so "Delivered" here means the module exists in this build, and "Planned" means
 * it does not.
 */
const PHASES = [
  { phase: 'Phase 1', title: 'Platform foundation', status: 'Delivered', detail: 'Authentication, ten roles, database schema, API foundation and application shell.' },
  { phase: 'Phase 2', title: 'Beekeeper & KVIC workflows', status: 'Delivered', detail: 'Beekeeper records, verification workflow, KVIC clusters, profiles and audit logs.' },
  { phase: 'Phase 3', title: 'Hive registry & IoT foundation', status: 'Delivered', detail: 'Hive registry, IoT devices, sensor configuration, telemetry ingest over HTTP or MQTT, and monitoring screens.' },
  { phase: 'Phase 4', title: 'Traceability & blockchain', status: 'Planned', detail: 'Harvest records, honey batches, supply-chain events, anchoring and QR verification.' },
  { phase: 'Phase 5', title: 'AI intelligence', status: 'Planned', detail: 'Assisted analysis as decision support — risk signals and forecasting, never diagnosis.' },
  { phase: 'Phase 6', title: 'KVIC analytics', status: 'Planned', detail: 'Cluster dashboards, scheme reporting, production summaries and audit review.' },
];

export default function AboutPage() {
  return (
    <div className="hc-container py-12 sm:py-16">
      <SectionHeading
        eyebrow="About"
        title="Why HoneyChain exists"
        description="HoneyChain is a blockchain-based honey traceability and smart beekeeping management platform, developed against Smart India Hackathon 2026 Problem Statement 26021."
      />

      <div className="mt-10 grid gap-6 lg:grid-cols-[1.3fr_1fr]">
        <div className="space-y-5 text-sm leading-relaxed text-ink-soft">
          <p>
            Honey is sold on trust. A label often states a region and a floral source, but the buyer
            has no practical way to confirm that the jar came from where it says, was handled
            hygienically, or was tested at all. At the same time, beekeepers who do produce
            genuinely traceable honey have little means of proving it — and little data to improve
            their own apiary management.
          </p>
          <p>
            HoneyChain addresses both sides of that gap. It gives beekeepers a monitoring and record
            keeping workspace, gives every participant in the supply chain one shared batch
            identifier, and gives consumers a verification view derived from records that cannot be
            quietly altered after the fact.
          </p>
          <p>
            The platform is built to be extended: each capability (IoT ingest, AI insight,
            blockchain anchoring, QR issuance) is a module behind the same API and data model, so
            new functions are added without disturbing what already works.
          </p>

          <div className="rounded-card border border-sand-300 bg-white p-5">
            <h2 className="text-base font-semibold text-ink">What this release does and does not do</h2>
            <ul className="mt-3 space-y-2">
              <li>
                <strong className="text-ink">Available now:</strong> account creation and sign-in for
                all ten roles, role-based access to workspaces, the public site, and a verified
                database/API foundation.
              </li>
              <li>
                <strong className="text-ink">Not yet available:</strong> live hive data, batch and QR
                traceability, laboratory workflows, blockchain anchoring and AI insights. These are
                scheduled in the phases below and are not simulated in the interface.
              </li>
            </ul>
          </div>
        </div>

        <Card className="h-fit">
          <CardBody>
            <h2 className="text-base font-semibold text-ink">Development roadmap</h2>
            <ol className="mt-4 space-y-4">
              {PHASES.map((item) => (
                <li key={item.phase} className="border-l-2 border-sand-300 pl-4">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-mono text-xs text-honey-700">{item.phase}</span>
                    <Badge variant={item.status === 'Delivered' ? 'success' : 'pending'} size="sm">
                      {item.status}
                    </Badge>
                  </div>
                  <p className="mt-1 text-sm font-medium text-ink">{item.title}</p>
                  <p className="mt-0.5 text-sm text-ink-soft">{item.detail}</p>
                </li>
              ))}
            </ol>
          </CardBody>
        </Card>
      </div>
    </div>
  );
}
