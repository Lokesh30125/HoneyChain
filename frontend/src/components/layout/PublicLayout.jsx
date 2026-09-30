import { Outlet } from 'react-router-dom';

import { PublicFooter } from '@/components/layout/PublicFooter';
import { PublicHeader } from '@/components/layout/PublicHeader';

/** Shell for the public marketing pages: header, routed content, footer. */
export function PublicLayout() {
  return (
    <div className="flex min-h-screen flex-col bg-sand-50">
      <PublicHeader />
      <main id="main-content" className="flex-1 pb-8">
        <Outlet />
      </main>
      <PublicFooter />
    </div>
  );
}

export default PublicLayout;
