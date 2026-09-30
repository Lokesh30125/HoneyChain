import { Link } from 'react-router-dom';
import { motion } from 'framer-motion';
import {
  Activity,
  BadgeCheck,
  BookOpenCheck,
  Boxes,
  Building2,
  ClipboardCheck,
  FlaskConical,
  Gauge,
  GraduationCap,
  Landmark,
  Layers,
  Link2,
  Lock,
  MapPin,
  QrCode,
  Recycle,
  ScanLine,
  ServerCog,
  ShieldAlert,
  Signal,
  Smartphone,
  Sprout,
  Thermometer,
  TrendingUp,
  Truck,
  Users,
} from 'lucide-react';

import { Card, CardBody } from '@/components/ui/Card';
import { Badge } from '@/components/ui/Badge';
import { SectionHeading } from '@/components/common/SectionHeading';
import { ChainFlowStrip } from '@/components/landing/ChainFlow';

/**
 * Landing page content sections.
 *
 * All ten foundation sections live in one module of small, presentational
 * components. Copy is deliberately careful: the platform claims verification and
 * decision *support*, never guaranteed authenticity or complete disease
 * detection.
 */

/* ------------------------------------------------------------------ 1. Problem */
const PROBLEMS = [
  {
    Icon: ShieldAlert,
    title: 'Counterfeit and adulterated honey',
    body: 'Sugar syrups and low-grade imports are blended into honey, and buyers have almost no way to tell what is inside the jar.',
  },
  {
    Icon: Gauge,
    title: 'Weak traceability',
    body: 'Records are paper-based or spread across disconnected systems, so a batch cannot be followed convincingly from hive to shelf.',
  },
  {
    Icon: Signal,
    title: 'Unmonitored colonies',
    body: 'Most apiaries have no continuous visibility of hive temperature, humidity, weight or colony behaviour between inspections.',
  },
  {
    Icon: TrendingUp,
    title: 'Missed yield and market potential',
    body: 'Without structured records, beekeepers cannot demonstrate quality, negotiate fair prices, or plan harvesting for better yield.',
  },
  {
    Icon: GraduationCap,
    title: 'Limited access to advisory support',
    body: 'Disease suspicion and swarm behaviour are handled by experience alone, with little data to consult or share with experts.',
  },
  {
    Icon: Building2,
    title: 'Fragmented cluster oversight',
    body: 'KVIC and state agencies lack consolidated visibility of beekeeping clusters, capacity and scheme outcomes.',
  },
];

export function ProblemSection() {
  return (
    <section id="problem" className="border-b border-sand-200 bg-sand-50 py-14 sm:py-16">
      <div className="hc-container">
        <SectionHeading
          eyebrow="The problem"
          title="Honey is trusted on packaging, not on evidence"
          description="India is among the world's largest honey producers, yet the gap between what a label claims and what can actually be verified remains wide."
        />

        <div className="mt-10 grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
          {PROBLEMS.map(({ Icon, title, body }, index) => (
            <motion.div
              key={title}
              initial={{ opacity: 0, y: 10 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true, amount: 0.3 }}
              transition={{ duration: 0.3, delay: index * 0.04 }}
            >
              <Card className="h-full">
                <CardBody>
                  <span className="flex h-10 w-10 items-center justify-center rounded-lg bg-status-danger-bg text-status-danger">
                    <Icon size={19} aria-hidden="true" />
                  </span>
                  <h3 className="mt-4 text-base font-semibold text-ink">{title}</h3>
                  <p className="mt-1.5 text-sm leading-relaxed text-ink-soft">{body}</p>
                </CardBody>
              </Card>
            </motion.div>
          ))}
        </div>
      </div>
    </section>
  );
}

/* ----------------------------------------------------------------- 2. Solution */
const SOLUTION_PILLARS = [
  {
    Icon: Link2,
    title: 'One traceable record per batch',
    body: 'Harvest, collection, processing, testing, packaging and distribution events are written into a single chain of custody instead of six registers.',
  },
  {
    Icon: Activity,
    title: 'Hives that report their own state',
    body: 'IoT nodes publish sensor readings continuously, so an apiary can be reviewed remotely and inspected when it actually matters.',
  },
  {
    Icon: FlaskConical,
    title: 'Quality results attached to the batch',
    body: 'Laboratory outcomes (moisture, HMF, purity indicators) stay linked to the exact batch they describe.',
  },
  {
    Icon: QrCode,
    title: 'Verification anyone can perform',
    body: 'A consumer scans a jar and sees the recorded journey and its verification status — in plain language.',
  },
  {
    Icon: Landmark,
    title: 'Cluster-level visibility for KVIC',
    body: 'Aggregated, privacy-aware views of clusters, capacity, quality outcomes and scheme participation.',
  },
  {
    Icon: Smartphone,
    title: 'Designed for field conditions',
    body: 'Clear layouts, minimal typing and low-bandwidth-tolerant pages so the system is usable from a phone in an apiary.',
  },
];

export function SolutionSection() {
  return (
    <section id="solution" className="border-b border-sand-200 bg-white py-14 sm:py-16">
      <div className="hc-container">
        <SectionHeading
          eyebrow="The solution"
          title="A single platform from hive to jar"
          description="HoneyChain joins six capabilities that are usually separate products: hive monitoring, batch traceability, laboratory records, packaging identity, distribution tracking and consumer verification."
        />

        <div className="mt-10 grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
          {SOLUTION_PILLARS.map(({ Icon, title, body }) => (
            <Card key={title} className="h-full border-sand-300">
              <CardBody>
                <span className="flex h-10 w-10 items-center justify-center rounded-lg bg-forest-50 text-forest-700">
                  <Icon size={19} aria-hidden="true" />
                </span>
                <h3 className="mt-4 text-base font-semibold text-ink">{title}</h3>
                <p className="mt-1.5 text-sm leading-relaxed text-ink-soft">{body}</p>
              </CardBody>
            </Card>
          ))}
        </div>
      </div>
    </section>
  );
}

/* --------------------------------------------------------------- 3. How it works */
const WORKFLOW_STEPS = [
  {
    step: '01',
    title: 'Register the hive',
    body: 'A beekeeper registers each hive with its location, colony details and an IoT device pairing. Every hive gets a permanent identifier.',
  },
  {
    step: '02',
    title: 'Monitor continuously',
    body: 'Sensor readings arrive from the hive gateway; the platform flags readings outside the expected range for that season.',
  },
  {
    step: '03',
    title: 'Record the harvest',
    body: 'At harvest, the beekeeper records quantity, date, floral source and hive. This becomes the parent record for a batch.',
  },
  {
    step: '04',
    title: 'Collect and process',
    body: 'Collection centres and processors append their events — intake weight, handling, processing parameters — to the same batch history.',
  },
  {
    step: '05',
    title: 'Test and package',
    body: 'Laboratory results and packaging events are attached to the batch, and a QR identity is issued for the packaged lot.',
  },
  {
    step: '06',
    title: 'Distribute and verify',
    body: 'Distribution and retail handoffs are recorded. A consumer scan resolves the whole history and its verification status.',
  },
];

export function HowItWorksSection() {
  return (
    <section id="how-it-works" className="border-b border-sand-200 bg-sand-100/60 py-14 sm:py-16">
      <div className="hc-container">
        <SectionHeading
          eyebrow="How HoneyChain works"
          title="Six stages, one continuous record"
          description="Each participant sees only their own tasks, but every entry contributes to the same batch history and is attributed to a verified account."
        />

        <ol className="mt-10 grid gap-5 md:grid-cols-2 lg:grid-cols-3">
          {WORKFLOW_STEPS.map((item) => (
            <li key={item.step}>
              <Card className="h-full">
                <CardBody>
                  <span className="font-mono text-xs font-semibold tracking-wider text-honey-700">
                    STEP {item.step}
                  </span>
                  <h3 className="mt-2 text-base font-semibold text-ink">{item.title}</h3>
                  <p className="mt-1.5 text-sm leading-relaxed text-ink-soft">{item.body}</p>
                </CardBody>
              </Card>
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
}

/* ------------------------------------------------------- 4. Smart beekeeping */
const BEEKEEPING_CAPABILITIES = [
  { Icon: Thermometer, label: 'Hive temperature and humidity trends' },
  { Icon: Activity, label: 'Hive weight tracking across a nectar flow' },
  { Icon: Signal, label: 'Acoustic and activity signals for colony state' },
  { Icon: ClipboardCheck, label: 'Inspection log with colony observations' },
  { Icon: Sprout, label: 'Floral source and season notes per hive' },
  { Icon: ShieldAlert, label: 'Health alerts for follow-up, not diagnosis' },
];

export function SmartBeekeepingSection() {
  return (
    <section id="beekeeping" className="border-b border-sand-200 bg-white py-14 sm:py-16">
      <div className="hc-container grid items-start gap-10 lg:grid-cols-2">
        <div>
          <SectionHeading
            eyebrow="Smart beekeeping"
            title="Decisions supported by the hive's own data"
            description="The beekeeper workspace is built around the questions an apiary actually raises: is the colony healthy, when should I harvest, and is this trend unusual for the season?"
          />

          <div className="mt-8 grid gap-3 sm:grid-cols-2">
            {BEEKEEPING_CAPABILITIES.map(({ Icon, label }) => (
              <div
                key={label}
                className="flex items-start gap-3 rounded-lg border border-sand-300 bg-sand-50 px-3.5 py-3"
              >
                <Icon size={17} className="mt-0.5 flex-none text-forest-600" aria-hidden="true" />
                <span className="text-sm text-ink-soft">{label}</span>
              </div>
            ))}
          </div>

          <p className="mt-6 rounded-lg border border-honey-300 bg-honey-50 px-4 py-3 text-sm text-ink-soft">
            <strong className="text-ink">How AI is used here.</strong> Models highlight unusual
            patterns and estimate yield ranges to support the beekeeper&apos;s judgement. They do not
            diagnose disease and never replace an inspection or a laboratory test.
          </p>
        </div>

        <Card className="bg-forest-900 text-sand-200">
          <CardBody className="space-y-4">
            <h3 className="text-base font-semibold text-white">What a beekeeper sees</h3>
            <p className="text-sm text-sand-300">
              A per-hive summary that combines sensor ranges, inspection notes and harvest history
              into a single view — designed to be read in under a minute before an inspection.
            </p>
            <ul className="space-y-3 text-sm">
              {[
                'Hive status: last reading, deviations from the seasonal band, device uptime.',
                'Harvest planning: weight gain trend and days since the last harvest.',
                'Risk signals: readings or patterns flagged for a closer look.',
                'Traceability: every harvest already linked to a batch identity.',
              ].map((line) => (
                <li key={line} className="flex gap-3">
                  <BadgeCheck size={17} className="mt-0.5 flex-none text-honey-400" aria-hidden="true" />
                  <span className="text-sand-300">{line}</span>
                </li>
              ))}
            </ul>
            <p className="text-xs text-sand-400">
              Sensor-led features are delivered in Phase 4 (IoT) and Phase 5 (AI). Phase 1
              establishes accounts, roles and the platform shell.
            </p>
          </CardBody>
        </Card>
      </div>
    </section>
  );
}

/* ----------------------------------------------------- 5. Blockchain traceability */
export function BlockchainTraceabilitySection() {
  return (
    <section id="traceability" className="border-b border-sand-200 bg-sand-100/60 py-14 sm:py-16">
      <div className="hc-container">
        <SectionHeading
          eyebrow="Blockchain traceability"
          title="Records that can be checked, not just claimed"
          description="Each significant event is hashed, timestamped and anchored, then linked to the previous entry for that batch. Altering a past record breaks the chain and is detectable — which is what makes the history trustworthy."
        />

        <div className="mt-10 grid gap-6 lg:grid-cols-3">
          <Card>
            <CardBody>
              <span className="flex h-10 w-10 items-center justify-center rounded-lg bg-honey-50 text-honey-700">
                <Layers size={19} aria-hidden="true" />
              </span>
              <h3 className="mt-4 text-base font-semibold text-ink">Event anchoring</h3>
              <p className="mt-1.5 text-sm leading-relaxed text-ink-soft">
                Harvest, collection, processing, test, packaging and distribution events are hashed
                with their payload and anchored, so the record cannot be quietly edited later.
              </p>
            </CardBody>
          </Card>

          <Card>
            <CardBody>
              <span className="flex h-10 w-10 items-center justify-center rounded-lg bg-forest-50 text-forest-700">
                <Boxes size={19} aria-hidden="true" />
              </span>
              <h3 className="mt-4 text-base font-semibold text-ink">Batch lineage</h3>
              <p className="mt-1.5 text-sm leading-relaxed text-ink-soft">
                Batches can be split when packaging and combined when blending. The parent-child
                links are recorded, so a jar can be traced back through every split to source hives.
              </p>
            </CardBody>
          </Card>

          <Card>
            <CardBody>
              <span className="flex h-10 w-10 items-center justify-center rounded-lg bg-status-info-bg text-status-info">
                <BookOpenCheck size={19} aria-hidden="true" />
              </span>
              <h3 className="mt-4 text-base font-semibold text-ink">Independent verification</h3>
              <p className="mt-1.5 text-sm leading-relaxed text-ink-soft">
                A verifier — a buyer, an auditor or the platform itself — can recompute the hash of a
                recorded event and confirm it still matches what was anchored.
              </p>
            </CardBody>
          </Card>
        </div>

        <div className="mt-8 rounded-card border border-sand-300 bg-white p-5">
          <p className="mb-3 text-sm font-medium text-ink">The record that travels with a batch</p>
          <ChainFlowStrip />
        </div>

        <p className="mt-6 flex items-start gap-2 text-sm text-ink-muted">
          <Lock size={16} className="mt-0.5 flex-none" aria-hidden="true" />
          <span>
            Blockchain is used for integrity and provenance — not for tokens or speculation.
            Anchoring is implemented in Phase 3; this release provides the identity and role
            foundation it depends on.
          </span>
        </p>
      </div>
    </section>
  );
}

/* ------------------------------------------------------ 6. Consumer verification */
export function ConsumerVerificationSection() {
  return (
    <section id="consumer" className="border-b border-sand-200 bg-white py-14 sm:py-16">
      <div className="hc-container grid items-start gap-10 lg:grid-cols-[1fr_0.9fr]">
        <div>
          <SectionHeading
            eyebrow="Consumer verification"
            title="What a scan should tell you"
            description="A QR code on the jar resolves to the batch record. The consumer view answers the questions people actually ask at the shelf — without jargon and without overstating certainty."
          />

          <ul className="mt-8 space-y-4">
            {[
              {
                title: 'Where it came from',
                body: 'Origin region, apiary and harvest date, plus the floral source where it was recorded.',
              },
              {
                title: 'How it was handled',
                body: 'Collection, processing and packaging events with their dates and the responsible organisations.',
              },
              {
                title: 'What was tested',
                body: 'Laboratory results recorded for that batch, with the testing laboratory and sample date.',
              },
              {
                title: 'Whether the record checks out',
                body: 'Verification status of the anchored history — including when the code is unknown or a batch has no quality record yet.',
              },
            ].map((item) => (
              <li key={item.title} className="flex gap-3">
                <span className="mt-1 flex h-6 w-6 flex-none items-center justify-center rounded-full bg-honey-500 text-xs font-semibold text-forest-900">
                  ✓
                </span>
                <div>
                  <p className="text-sm font-semibold text-ink">{item.title}</p>
                  <p className="mt-0.5 text-sm leading-relaxed text-ink-soft">{item.body}</p>
                </div>
              </li>
            ))}
          </ul>

          <p className="mt-6 rounded-lg border border-status-info/25 bg-status-info-bg px-4 py-3 text-sm text-status-info">
            HoneyChain reports what was recorded and whether it verifies. It does not declare a jar
            &quot;100% pure&quot; — authenticity claims remain the responsibility of accredited
            laboratories and regulators.
          </p>
        </div>

        {/* Static illustration of the future consumer screen. */}
        <Card className="mx-auto w-full max-w-sm overflow-hidden">
          <div className="bg-forest-900 px-5 py-4 text-white">
            <p className="text-xs uppercase tracking-wide text-honey-300">Batch verification</p>
            <p className="mt-1 font-mono text-sm">HC-BATCH-2026-000184</p>
          </div>
          <CardBody className="space-y-4">
            <div className="flex items-center justify-between rounded-lg border border-sand-300 bg-sand-50 px-3.5 py-3">
              <span className="text-sm text-ink-soft">Record integrity</span>
              <Badge variant="success" size="sm">
                Verified
              </Badge>
            </div>
            {[
              { Icon: MapPin, label: 'Origin', value: 'Guntur district, Andhra Pradesh' },
              { Icon: Boxes, label: 'Harvested', value: 'Recorded with hive reference' },
              { Icon: Truck, label: 'Handled by', value: 'Collection centre → processor' },
              { Icon: FlaskConical, label: 'Lab tests', value: 'Results attached to batch' },
            ].map(({ Icon, label, value }) => (
              <div key={label} className="flex items-start gap-3">
                <Icon size={16} className="mt-0.5 flex-none text-forest-600" aria-hidden="true" />
                <div>
                  <p className="text-xs uppercase tracking-wide text-ink-muted">{label}</p>
                  <p className="text-sm text-ink-soft">{value}</p>
                </div>
              </div>
            ))}
            <p className="border-t border-sand-200 pt-3 text-xs text-ink-muted">
              Illustrative layout. QR scanning and the public verification page arrive in Phase 3.
            </p>
          </CardBody>
        </Card>
      </div>
    </section>
  );
}

/* -------------------------------------------------------------- 7. AI intelligence */
const AI_CAPABILITIES = [
  {
    Icon: ShieldAlert,
    title: 'Risk signals for colony health',
    body: 'Combines sensor trends, inspection notes and season to flag hives worth an early look.',
  },
  {
    Icon: TrendingUp,
    title: 'Harvest and yield forecasting',
    body: 'Estimates yield ranges from hive weight patterns and historical harvests to help plan collection.',
  },
  {
    Icon: FlaskConical,
    title: 'Adulteration screening support',
    body: 'Highlights batches whose recorded test parameters look inconsistent for their declared origin.',
  },
  {
    Icon: ServerCog,
    title: 'Decision support, not automation',
    body: 'Every output is advisory, shows the factors behind it, and stays reviewable by a human expert.',
  },
];

export function AiIntelligenceSection() {
  return (
    <section id="ai" className="border-b border-sand-200 bg-sand-50 py-14 sm:py-16">
      <div className="hc-container">
        <SectionHeading
          eyebrow="AI intelligence"
          title="AI-assisted insight, with limits stated plainly"
          description="Models help people notice things earlier and plan better. They are evaluated for their accuracy, and their output is presented as a risk indicator with its reasoning — never as a verdict."
        />

        <div className="mt-10 grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
          {AI_CAPABILITIES.map(({ Icon, title, body }) => (
            <Card key={title} className="h-full">
              <CardBody>
                <span className="flex h-10 w-10 items-center justify-center rounded-lg bg-status-pending-bg text-status-pending">
                  <Icon size={19} aria-hidden="true" />
                </span>
                <h3 className="mt-4 text-sm font-semibold text-ink">{title}</h3>
                <p className="mt-1.5 text-sm leading-relaxed text-ink-soft">{body}</p>
              </CardBody>
            </Card>
          ))}
        </div>
      </div>
    </section>
  );
}

/* --------------------------------------------------------------- 8. Rural / KVIC */
const IMPACT_POINTS = [
  {
    Icon: Users,
    title: 'Support for small and marginal beekeepers',
    body: 'Simple screens, regional language readiness and role-based access that does not require technical training.',
  },
  {
    Icon: Building2,
    title: 'Cluster-level monitoring',
    body: 'KVIC officers see cluster participation, hive counts, harvest volumes and quality outcomes in aggregate.',
  },
  {
    Icon: Sprout,
    title: 'Stronger market linkage',
    body: 'Verifiable quality records give buyers a reason to pay for documented honey rather than anonymous supply.',
  },
  {
    Icon: Recycle,
    title: 'Consistent records across the chain',
    body: 'Collection centres, processors and packagers work from the same identifiers, reducing disputes and re-entry.',
  },
];

export function RuralImpactSection() {
  return (
    <section id="impact" className="border-b border-sand-200 bg-white py-14 sm:py-16">
      <div className="hc-container">
        <SectionHeading
          eyebrow="Rural and KVIC impact"
          title="Built to scale across beekeeping clusters"
          description="The platform is designed for the way beekeeping is actually organised in India — individual apiaries, co-operatives, self-help groups and KVIC-backed clusters."
        />

        <div className="mt-10 grid gap-5 sm:grid-cols-2">
          {IMPACT_POINTS.map(({ Icon, title, body }) => (
            <Card key={title} className="h-full border-sand-300">
              <CardBody className="flex gap-4">
                <span className="flex h-10 w-10 flex-none items-center justify-center rounded-lg bg-forest-50 text-forest-700">
                  <Icon size={19} aria-hidden="true" />
                </span>
                <div>
                  <h3 className="text-base font-semibold text-ink">{title}</h3>
                  <p className="mt-1 text-sm leading-relaxed text-ink-soft">{body}</p>
                </div>
              </CardBody>
            </Card>
          ))}
        </div>
      </div>
    </section>
  );
}

/* -------------------------------------------------------------- 9. Technology */
const TECH_LAYERS = [
  {
    title: 'Client',
    items: ['React single-page application', 'Role-aware dashboards', 'QR verification page'],
  },
  {
    title: 'API',
    items: ['FastAPI REST service (versioned /api/v1)', 'JWT access + rotating refresh tokens', 'Role-based access control'],
  },
  {
    title: 'Data',
    items: ['PostgreSQL with SQLAlchemy models', 'Alembic migrations', 'Repositories separated from business logic'],
  },
  {
    title: 'Platform services',
    items: ['Blockchain anchoring (Phase 3)', 'MQTT IoT ingest (Phase 4)', 'AI inference service (Phase 5)'],
  },
];

export function TechArchitectureSection() {
  return (
    <section id="technology" className="border-b border-sand-200 bg-sand-100/60 py-14 sm:py-16">
      <div className="hc-container">
        <SectionHeading
          eyebrow="Technology"
          title="A layered architecture meant to grow phase by phase"
          description="Each capability is added as its own module behind the same API and data model, so the platform can expand without rewriting what already works."
        />

        <div className="mt-10 grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
          {TECH_LAYERS.map((layer) => (
            <Card key={layer.title} className="h-full">
              <CardBody>
                <Badge variant="honey" size="sm">
                  {layer.title}
                </Badge>
                <ul className="mt-4 space-y-2.5">
                  {layer.items.map((item) => (
                    <li key={item} className="flex gap-2 text-sm text-ink-soft">
                      <span className="mt-2 h-1.5 w-1.5 flex-none rounded-full bg-honey-500" aria-hidden="true" />
                      {item}
                    </li>
                  ))}
                </ul>
              </CardBody>
            </Card>
          ))}
        </div>

        <div className="mt-8 flex flex-wrap items-center gap-3 rounded-card border border-sand-300 bg-white px-5 py-4 text-sm text-ink-muted">
          <ScanLine size={18} className="text-forest-600" aria-hidden="true" />
          <span>
            Phase 1 (this release) delivers the foundation: authentication, ten roles, the
            application shell and the database layer that later modules build on.
          </span>
        </div>
      </div>
    </section>
  );
}

/* -------------------------------------------------------------------- 10. CTA */
export function CallToActionSection() {
  return (
    <section className="bg-forest-900 py-14 text-white sm:py-16">
      <div className="hc-container flex flex-col items-start justify-between gap-8 lg:flex-row lg:items-center">
        <div className="max-w-2xl">
          <h2 className="text-2xl font-semibold tracking-tight text-white sm:text-3xl">
            Join the pilot as a beekeeper, cluster or supply-chain partner
          </h2>
          <p className="mt-3 text-base text-sand-300">
            Create an account to see your role workspace today: register hives, pair a sensor node
            and read live telemetry. Batch traceability, blockchain anchoring and the customer's QR
            verification page are live as well — any jar's label can be scanned without an account.
          </p>
        </div>
        <div className="flex flex-wrap gap-3">
          <Link
            to="/register"
            className="inline-flex h-12 items-center rounded-lg bg-honey-500 px-6 text-sm font-semibold text-forest-900 transition-colors hover:bg-honey-400"
          >
            Create an account
          </Link>
          <Link
            to="/how-it-works"
            className="inline-flex h-12 items-center rounded-lg border border-white/25 bg-white/5 px-6 text-sm font-medium text-white transition-colors hover:bg-white/10"
          >
            Read the walkthrough
          </Link>
        </div>
      </div>
    </section>
  );
}
