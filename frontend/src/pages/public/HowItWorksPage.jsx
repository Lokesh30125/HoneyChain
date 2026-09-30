import { Link } from 'react-router-dom';

import { SectionHeading } from '@/components/common/SectionHeading';
import { Card, CardBody } from '@/components/ui/Card';
import { Badge } from '@/components/ui/Badge';
import { ChainFlowStrip } from '@/components/landing/ChainFlow';
import { HowItWorksSection } from '@/components/landing/LandingSections';
import { ROLES, ROLE_DESCRIPTIONS, roleLabel } from '@/constants/roles';

/**
 * "How It Works" — the walkthrough page.
 *
 * Reuses the landing workflow section and expands on what each role can do,
 * which is exactly the question new users of a multi-role platform ask first.
 */
export default function HowItWorksPage() {
  return (
    <div>
      <section className="border-b border-sand-200 bg-forest-900 py-12 text-white">
        <div className="hc-container">
          <h1 className="text-3xl font-semibold tracking-tight text-white">How HoneyChain works</h1>
          <p className="mt-3 max-w-3xl text-base text-sand-200">
            One batch record, many contributors. Each participant records only what they are
            responsible for, and the platform keeps the whole history connected.
          </p>
          <div className="mt-7 rounded-card border border-white/15 bg-white/[0.06] p-4">
            <ChainFlowStrip />
          </div>
        </div>
      </section>

      <HowItWorksSection />

      <section className="bg-white py-14 sm:py-16">
        <div className="hc-container">
          <SectionHeading
            eyebrow="Roles"
            title="Who does what"
            description="Ten roles share a single sign-in. The workspace a person lands on depends on their role, and the API enforces the same rules on every request."
          />

          <div className="mt-10 grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
            {Object.values(ROLES).map((role) => (
              <Card key={role} className="h-full">
                <CardBody>
                  <div className="flex items-center justify-between gap-2">
                    <h3 className="text-base font-semibold text-ink">{roleLabel(role)}</h3>
                    <Badge variant="forest" size="sm">
                      {role}
                    </Badge>
                  </div>
                  <p className="mt-2 text-sm leading-relaxed text-ink-soft">
                    {ROLE_DESCRIPTIONS[role]}
                  </p>
                </CardBody>
              </Card>
            ))}
          </div>

          <p className="mt-8 text-sm text-ink-muted">
            Ready to try it?{' '}
            <Link to="/register" className="hc-link">
              Create an account
            </Link>{' '}
            or{' '}
            <Link to="/login" className="hc-link">
              sign in
            </Link>
            .
          </p>
        </div>
      </section>
    </div>
  );
}
