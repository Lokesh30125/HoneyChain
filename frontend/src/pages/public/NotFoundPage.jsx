import { Link } from 'react-router-dom';
import { Compass } from 'lucide-react';

import { Button } from '@/components/ui/Button';

/** 404 page. Kept public so it renders whether or not the user is signed in. */
export default function NotFoundPage() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-sand-50 px-4">
      <div className="max-w-lg text-center">
        <span className="mx-auto flex h-14 w-14 items-center justify-center rounded-full bg-honey-50 text-honey-700">
          <Compass size={26} aria-hidden="true" />
        </span>
        <p className="mt-5 font-mono text-sm text-ink-muted">404</p>
        <h1 className="mt-2 text-2xl font-semibold text-ink">This page could not be found</h1>
        <p className="mt-2 text-sm text-ink-soft">
          The link may be outdated, or the page may belong to a module that has not been released
          yet.
        </p>
        <div className="mt-6 flex flex-wrap justify-center gap-3">
          <Button to="/">Back to home</Button>
          <Button to="/dashboard" variant="secondary">
            Go to dashboard
          </Button>
        </div>
        <p className="mt-6 text-sm text-ink-muted">
          Looking for a verified jar?{' '}
          <Link to="/#consumer" className="hc-link">
            See how consumer verification works
          </Link>
          .
        </p>
      </div>
    </div>
  );
}
