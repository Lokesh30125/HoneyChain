import { motion } from 'framer-motion';
import { ArrowRight, BadgeCheck, Cpu, QrCode, ShieldCheck } from 'lucide-react';

import { Button } from '@/components/ui/Button';
import { ChainFlow } from '@/components/landing/ChainFlow';

/**
 * Hero.
 *
 * Communicates the whole proposition — hive to consumer — and shows the pipeline
 * (Hive → IoT → AI → Harvest → Quality → Blockchain → QR → Consumer) so a
 * visitor understands the system in one screen.
 */
export function HeroSection() {
  return (
    <section className="relative overflow-hidden border-b border-sand-200 bg-gradient-to-b from-forest-900 to-forest-800 text-white">
      <div className="hc-honeycomb absolute inset-0 opacity-30" aria-hidden="true" />

      <div className="hc-container relative py-14 sm:py-20">
        <div className="grid items-center gap-12 lg:grid-cols-[1.05fr_0.95fr]">
          <motion.div
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.4, ease: 'easeOut' }}
          >
            <span className="inline-flex items-center gap-2 rounded-full border border-honey-500/40 bg-honey-500/10 px-3 py-1 text-xs font-medium text-honey-200">
              <ShieldCheck size={14} aria-hidden="true" />
              Smart India Hackathon 2026 · Problem Statement 26021
            </span>

            <h1 className="mt-5 text-3xl font-semibold leading-tight tracking-tight text-white sm:text-4xl lg:text-[2.75rem]">
              Blockchain-powered honey traceability and AI-assisted smart beekeeping.
            </h1>

            <p className="mt-5 max-w-2xl text-base leading-relaxed text-sand-200 sm:text-lg">
              HoneyChain records every step a jar of honey takes — from a monitored hive, through
              collection, processing, laboratory testing and packaging — and anchors those records
              so the journey can be verified later. Beekeepers get hive and colony insights;
              consumers get authenticity verification; KVIC gets cluster-level visibility.
            </p>

            <div className="mt-8 flex flex-wrap gap-3">
              <Button to="/register" variant="accent" size="lg" rightIcon={<ArrowRight size={18} />}>
                Register as a beekeeper
              </Button>
              <Button
                to="/how-it-works"
                size="lg"
                variant="secondary"
                className="border-white/25 bg-white/5 text-white hover:bg-white/10"
              >
                See how it works
              </Button>
            </div>

            <dl className="mt-10 grid gap-6 sm:grid-cols-3">
              <div>
                <dt className="flex items-center gap-2 text-sm font-medium text-honey-200">
                  <QrCode size={16} aria-hidden="true" />
                  Consumer verification
                </dt>
                <dd className="mt-1 text-sm text-sand-300">
                  Scan a jar&apos;s QR code to see its recorded journey.
                </dd>
              </div>
              <div>
                <dt className="flex items-center gap-2 text-sm font-medium text-honey-200">
                  <Cpu size={16} aria-hidden="true" />
                  IoT hive monitoring
                </dt>
                <dd className="mt-1 text-sm text-sand-300">
                  Temperature, humidity, weight and acoustic signals per hive.
                </dd>
              </div>
              <div>
                <dt className="flex items-center gap-2 text-sm font-medium text-honey-200">
                  <BadgeCheck size={16} aria-hidden="true" />
                  Immutable records
                </dt>
                <dd className="mt-1 text-sm text-sand-300">
                  Traceability entries recorded once and independently verifiable.
                </dd>
              </div>
            </dl>
          </motion.div>

          <motion.div
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, delay: 0.1, ease: 'easeOut' }}
            className="rounded-card border border-white/15 bg-white/[0.06] p-5 backdrop-blur-sm"
          >
            <p className="text-sm font-medium text-white">The traceability pipeline</p>
            <p className="mt-1 text-sm text-sand-300">
              Every stage contributes a record; nothing is entered without a responsible actor and
              a timestamp.
            </p>
            <div className="mt-5">
              <ChainFlow />
            </div>
          </motion.div>
        </div>
      </div>
    </section>
  );
}

export default HeroSection;
