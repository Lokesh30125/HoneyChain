import {
  Activity,
  BrainCircuit,
  ClipboardCheck,
  Boxes,
  Focus,
  Link2,
  QrCode,
  ShoppingBasket,
} from 'lucide-react';

/**
 * Visualises the HoneyChain pipeline:
 * Hive → IoT → AI → Harvest → Quality → Blockchain → QR → Consumer
 *
 * Data-driven so later phases can reuse it to show live stage status on the
 * traceability screen (pending / recorded / verified) instead of a static list.
 */

export const PIPELINE_STAGES = [
  {
    key: 'HIVE',
    label: 'Hive',
    detail: 'Registered hive with an owner, location and colony record.',
    Icon: Focus,
  },
  {
    key: 'IOT',
    label: 'IoT sensors',
    detail: 'Temperature, humidity, hive weight and acoustic readings stream in.',
    Icon: Activity,
  },
  {
    key: 'AI',
    label: 'AI assistance',
    detail: 'Anomaly and risk signals, swarm timing and yield forecasting.',
    Icon: BrainCircuit,
  },
  {
    key: 'HARVEST',
    label: 'Harvest',
    detail: 'Beekeeper records the harvest: date, quantity, floral source.',
    Icon: Boxes,
  },
  {
    key: 'QUALITY',
    label: 'Quality',
    detail: 'Laboratory tests for moisture, HMF, purity and adulteration screening.',
    Icon: ClipboardCheck,
  },
  {
    key: 'BLOCKCHAIN',
    label: 'Blockchain record',
    detail: 'Each event is hashed, timestamped and anchored immutably.',
    Icon: Link2,
  },
  {
    key: 'QR',
    label: 'QR code',
    detail: 'A jar-level identifier links the package to its trace record.',
    Icon: QrCode,
  },
  {
    key: 'CONSUMER',
    label: 'Consumer',
    detail: 'Scan to view origin, handling and test results before buying.',
    Icon: ShoppingBasket,
  },
];

export function ChainFlow({ stages = PIPELINE_STAGES, compact = false }) {
  return (
    <ol className="space-y-0" aria-label="HoneyChain traceability pipeline">
      {stages.map((stage, index) => {
        const { Icon } = stage;
        return (
          <li key={stage.key} className="flex gap-3">
            <div className="flex flex-none flex-col items-center">
              <span className="flex h-8 w-8 items-center justify-center rounded-full border border-honey-500/40 bg-honey-500/10 text-honey-300">
                <Icon size={15} aria-hidden="true" />
              </span>
              {index < stages.length - 1 ? (
                <span className="my-1 w-px flex-1 bg-white/20" aria-hidden="true" />
              ) : null}
            </div>
            <div className={index < stages.length - 1 ? 'pb-4' : ''}>
              <p className="text-sm font-medium text-white">{stage.label}</p>
              {!compact ? <p className="mt-0.5 text-xs leading-relaxed text-sand-300">{stage.detail}</p> : null}
            </div>
          </li>
        );
      })}
    </ol>
  );
}

/** Reusable horizontal variant showing the same pipeline as a linear strip. */
export function ChainFlowStrip() {
  return (
    <div className="flex flex-wrap items-center gap-2" role="list" aria-label="Pipeline stages">
      {PIPELINE_STAGES.map((stage, index) => (
        <div key={stage.key} className="flex items-center gap-2" role="listitem">
          <span className="rounded-full border border-sand-300 bg-white px-3 py-1 text-xs font-medium text-ink-soft">
            {stage.label}
          </span>
          {index < PIPELINE_STAGES.length - 1 ? (
            <span className="text-sand-400" aria-hidden="true">
              →
            </span>
          ) : null}
        </div>
      ))}
    </div>
  );
}

export default ChainFlow;
