import { HeroSection } from '@/components/landing/HeroSection';
import {
  AiIntelligenceSection,
  BlockchainTraceabilitySection,
  CallToActionSection,
  ConsumerVerificationSection,
  HowItWorksSection,
  ProblemSection,
  RuralImpactSection,
  SmartBeekeepingSection,
  SolutionSection,
  TechArchitectureSection,
} from '@/components/landing/LandingSections';

/**
 * Public landing page.
 *
 * Composed from section components rather than written inline so each block can
 * be edited (or reused on /how-it-works) independently.
 */
export default function LandingPage() {
  return (
    <>
      <HeroSection />
      <ProblemSection />
      <SolutionSection />
      <HowItWorksSection />
      <SmartBeekeepingSection />
      <BlockchainTraceabilitySection />
      <ConsumerVerificationSection />
      <AiIntelligenceSection />
      <RuralImpactSection />
      <TechArchitectureSection />
      <CallToActionSection />
    </>
  );
}
