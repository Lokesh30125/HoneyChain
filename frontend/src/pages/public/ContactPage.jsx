import { Building2, Mail, MapPin, Phone } from 'lucide-react';

import { Card, CardBody } from '@/components/ui/Card';
import { SectionHeading } from '@/components/common/SectionHeading';

/**
 * Contact page.
 *
 * Deliberately informational in Phase 1: there is no contact-message endpoint
 * yet, so the page does not pretend to submit anything. A real enquiry form
 * (with persistence and notification) is scheduled for a later phase.
 */
const CONTACTS = [
  {
    Icon: Mail,
    label: 'Programme email',
    value: 'hello@honeychain.example.org',
    hint: 'Replace with the programme mailbox before deployment.',
  },
  {
    Icon: Phone,
    label: 'Helpline',
    value: '+91 00000 00000',
    hint: 'Toll-free support line for beekeeper onboarding (placeholder).',
  },
  {
    Icon: MapPin,
    label: 'Programme office',
    value: 'Khadi and Village Industries Commission',
    hint: 'Cluster onboarding and pilot coordination.',
  },
  {
    Icon: Building2,
    label: 'For institutions',
    value: 'Labs, processors and exporters',
    hint: 'Integration and API access enquiries.',
  },
];

export default function ContactPage() {
  return (
    <div className="hc-container py-12 sm:py-16">
      <SectionHeading
        eyebrow="Contact"
        title="Talk to the HoneyChain team"
        description="For pilot participation, cluster onboarding or integration questions."
      />

      <div className="mt-10 grid gap-5 sm:grid-cols-2">
        {CONTACTS.map(({ Icon, label, value, hint }) => (
          <Card key={label}>
            <CardBody className="flex gap-4">
              <span className="flex h-10 w-10 flex-none items-center justify-center rounded-lg bg-forest-50 text-forest-700">
                <Icon size={19} aria-hidden="true" />
              </span>
              <div>
                <p className="text-xs uppercase tracking-wide text-ink-muted">{label}</p>
                <p className="mt-0.5 font-medium text-ink">{value}</p>
                <p className="mt-1 text-sm text-ink-soft">{hint}</p>
              </div>
            </CardBody>
          </Card>
        ))}
      </div>

      <p className="mt-8 max-w-3xl rounded-card border border-status-warning/30 bg-status-warning-bg px-5 py-4 text-sm text-status-warning">
        These contact details are placeholders for the prototype. An enquiry form with ticket
        tracking will be added alongside the notification module.
      </p>
    </div>
  );
}
