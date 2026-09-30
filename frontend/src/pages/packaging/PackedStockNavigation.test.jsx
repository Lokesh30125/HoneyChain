import { render, screen, waitFor, within, act } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { RouterProvider, createMemoryRouter, useLocation } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { PackagingWorkspace } from '@/components/packaging/PackagingWorkspace';
import PackageInformationPage from '@/pages/packaging/PackageInformationPage';
import { ToastProvider } from '@/context/ToastContext';
import { ROLES } from '@/constants/roles';
import * as packagingService from '@/services/packagingService';
import * as blockchainService from '@/services/blockchainService';

/**
 * Packed stock → package information → QR label.
 *
 * The services are the only thing faked (they are the HTTP boundary). The
 * workspace, the register table, the detail page and PackageQrLabel are the real
 * components, mounted on the real route shapes from AppRoutes.
 */

vi.mock('@/services/packagingService');
vi.mock('@/services/blockchainService', async (importOriginal) => {
  const actual = await importOriginal();
  return { ...actual, getPackageQr: vi.fn(), issuePackageQr: vi.fn() };
});

// Two packages with distinct, non-sequential ids so a hardcoded or index-based id
// would fail the assertions below.
const PACKAGES = [
  {
    id: 'pkg-7f3a-0014',
    package_code: 'HC-PKG-2026-000014',
    batch_code: 'HC-BATCH-2026-000009',
    collection_code: 'HC-COL-2026-000031',
    beekeeper_name: 'Asha Rao',
    cluster_name: 'Araku Cluster',
    packaging_code: 'HC-PACK-2026-000004',
    packaging_unit_name: 'Vizag Packing Unit',
    package_size: 500,
    quantity: 500,
    unit: 'G',
    unit_label: 'g',
    packaging_type: 'GLASS_JAR',
    packaging_type_display: 'Glass jar',
    packaging_date: '2026-09-20',
    status: 'CREATED',
    status_label: 'Created',
    can_release: true,
    dispatched_quantity: 0,
    remaining_quantity: 500,
    shipment_count: 0,
    created_at: '2026-09-20T08:00:00Z',
    traceability: [],
  },
  {
    id: 'pkg-c91d-0015',
    package_code: 'HC-PKG-2026-000015',
    batch_code: 'HC-BATCH-2026-000009',
    collection_code: 'HC-COL-2026-000031',
    beekeeper_name: 'Asha Rao',
    cluster_name: 'Araku Cluster',
    packaging_code: 'HC-PACK-2026-000004',
    packaging_unit_name: 'Vizag Packing Unit',
    package_size: 250,
    quantity: 250,
    unit: 'G',
    unit_label: 'g',
    packaging_type: 'GLASS_JAR',
    packaging_type_display: 'Glass jar',
    packaging_date: '2026-09-20',
    status: 'CREATED',
    status_label: 'Created',
    can_release: false,
    dispatched_quantity: 0,
    remaining_quantity: 250,
    shipment_count: 0,
    created_at: '2026-09-20T08:01:00Z',
    traceability: [],
  },
];

const ISSUED_QR = {
  package_id: 'pkg-7f3a-0014',
  package_code: 'HC-PKG-2026-000014',
  batch_code: 'HC-BATCH-2026-000009',
  qr_id: 'QR-HC-PKG-2026-000014',
  qr_payload: 'https://honeychain.example/trace/HC-PKG-2026-000014',
  svg: '<svg data-testid="qr-svg" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"></svg>',
  generated_at: '2026-09-30T09:00:00Z',
  event_id: 'EVT-1',
  tx_id: null,
  scans: 0,
};

function LocationProbe() {
  const location = useLocation();
  return <div data-testid="location">{location.pathname}</div>;
}

function makeRouter(initialEntries, initialIndex) {
  return createMemoryRouter(
    [
      {
        path: '/packaging/stock',
        element: (
          <>
            <LocationProbe />
            <PackagingWorkspace role={ROLES.PACKAGING_UNIT} view="packages" />
          </>
        ),
      },
      {
        path: '/packaging/packages/:packageId',
        element: (
          <>
            <LocationProbe />
            <PackageInformationPage />
          </>
        ),
      },
    ],
    { initialEntries, initialIndex },
  );
}

function mount(initialEntries = ['/packaging/stock'], initialIndex) {
  const router = makeRouter(initialEntries, initialIndex);
  const view = render(
    <ToastProvider>
      <RouterProvider router={router} />
    </ToastProvider>,
  );
  return { router, ...view };
}

const currentPath = () => screen.getByTestId('location').textContent;

beforeEach(() => {
  vi.clearAllMocks();

  packagingService.getPackagingSummary.mockResolvedValue(null);
  packagingService.listApprovedBatches.mockResolvedValue({ batches: [], meta: null });
  packagingService.listPackaging.mockResolvedValue({ runs: [], meta: null });
  packagingService.listPackages.mockResolvedValue({ packages: PACKAGES, meta: null });
  packagingService.listUnits.mockResolvedValue({ units: [] });
  packagingService.getMyUnit.mockResolvedValue(null);
  // The detail page reads the real package by the id in the URL.
  packagingService.getPackage.mockImplementation(async (id) => {
    const found = PACKAGES.find((p) => p.id === id);
    if (!found) throw new Error('not found');
    return found;
  });

  // No QR exists until one is generated.
  blockchainService.getPackageQr.mockResolvedValue({ package_code: 'HC-PKG-2026-000014', qr_payload: null });
  blockchainService.issuePackageQr.mockResolvedValue(ISSUED_QR);
});

describe('Packed stock → package information', () => {
  it('opens the real package when the package code is clicked', async () => {
    const user = userEvent.setup();
    mount();

    await user.click(await screen.findByRole('button', { name: 'HC-PKG-2026-000014' }));

    await waitFor(() => expect(currentPath()).toBe('/packaging/packages/pkg-7f3a-0014'));
    expect(packagingService.getPackage).toHaveBeenCalledWith('pkg-7f3a-0014');
    expect(await screen.findByRole('heading', { name: 'Package information' })).toBeInTheDocument();
  });

  it('opens the real package when the Open button is clicked', async () => {
    const user = userEvent.setup();
    mount();

    await screen.findByRole('button', { name: 'HC-PKG-2026-000015' });
    // Second row, so a wrong (first-row / hardcoded) id would be caught.
    const row = screen.getByRole('button', { name: 'HC-PKG-2026-000015' }).closest('tr');
    await user.click(within(row).getByRole('button', { name: 'Open' }));

    await waitFor(() => expect(currentPath()).toBe('/packaging/packages/pkg-c91d-0015'));
    expect(packagingService.getPackage).toHaveBeenCalledWith('pkg-c91d-0015');
  });

  it('loads the package detail with package, batch, collection and packaging information', async () => {
    const user = userEvent.setup();
    mount();
    await user.click(await screen.findByRole('button', { name: 'HC-PKG-2026-000014' }));

    // Package ID (code) + Batch ID + Collection are in the card header.
    expect(await screen.findByText('HC-BATCH-2026-000009 · HC-COL-2026-000031')).toBeInTheDocument();
    expect(screen.getAllByText('HC-PKG-2026-000014').length).toBeGreaterThan(0);
    // Packaging information.
    expect(screen.getByText('HC-PACK-2026-000004')).toBeInTheDocument();
    expect(screen.getByText('Vizag Packing Unit')).toBeInTheDocument();
    expect(screen.getByText('Glass jar')).toBeInTheDocument();
    // The existing QR label section is mounted for this package id.
    expect(await screen.findByText('QR label')).toBeInTheDocument();
    expect(blockchainService.getPackageQr).toHaveBeenCalledWith('pkg-7f3a-0014');
  });

  it('offers Generate QR when none exists, then shows the issued QR', async () => {
    const user = userEvent.setup();
    mount();
    await user.click(await screen.findByRole('button', { name: 'HC-PKG-2026-000014' }));

    await user.click(await screen.findByRole('button', { name: /Generate QR/ }));

    expect(blockchainService.issuePackageQr).toHaveBeenCalledWith('pkg-7f3a-0014');
    expect(await screen.findByTestId('qr-svg')).toBeInTheDocument();
    expect(screen.getByText('QR Generated ✓')).toBeInTheDocument();
    expect(screen.getByText('QR-HC-PKG-2026-000014')).toBeInTheDocument();
    expect(screen.getByText('Package ID')).toBeInTheDocument();
    const verification = screen.getByRole('link', { name: ISSUED_QR.qr_payload });
    expect(verification).toHaveAttribute('href', '/trace/HC-PKG-2026-000014');
    expect(screen.getByText('Open verification page')).toBeInTheDocument();
  });
});

describe('Refresh and browser history', () => {
  it('loads the same package when the detail URL is opened directly (refresh)', async () => {
    mount(['/packaging/packages/pkg-7f3a-0014']);

    expect(await screen.findByText('HC-BATCH-2026-000009 · HC-COL-2026-000031')).toBeInTheDocument();
    expect(packagingService.getPackage).toHaveBeenCalledWith('pkg-7f3a-0014');
    expect(await screen.findByText('QR label')).toBeInTheDocument();
  });

  it('survives a remount of the detail route mid-session (refresh after navigating)', async () => {
    const user = userEvent.setup();
    const first = mount();
    await user.click(await screen.findByRole('button', { name: 'HC-PKG-2026-000015' }));
    await waitFor(() => expect(currentPath()).toBe('/packaging/packages/pkg-c91d-0015'));
    const url = currentPath();
    first.unmount();

    packagingService.getPackage.mockClear();
    mount([url]);
    expect(await screen.findByText('HC-BATCH-2026-000009 · HC-COL-2026-000031')).toBeInTheDocument();
    expect(packagingService.getPackage).toHaveBeenCalledWith('pkg-c91d-0015');
  });

  it('supports browser back and forward between the list and the package', async () => {
    const user = userEvent.setup();
    const { router } = mount();

    await user.click(await screen.findByRole('button', { name: 'HC-PKG-2026-000014' }));
    await waitFor(() => expect(currentPath()).toBe('/packaging/packages/pkg-7f3a-0014'));
    await screen.findByText('QR label');

    // Back → Packed stock, still listing real rows.
    await act(async () => {
      await router.navigate(-1);
    });
    await waitFor(() => expect(currentPath()).toBe('/packaging/stock'));
    expect(await screen.findByRole('button', { name: 'HC-PKG-2026-000014' })).toBeInTheDocument();

    // Forward → the same package, loaded again.
    packagingService.getPackage.mockClear();
    await act(async () => {
      await router.navigate(1);
    });
    await waitFor(() => expect(currentPath()).toBe('/packaging/packages/pkg-7f3a-0014'));
    expect(await screen.findByText('HC-BATCH-2026-000009 · HC-COL-2026-000031')).toBeInTheDocument();
    expect(packagingService.getPackage).toHaveBeenCalledWith('pkg-7f3a-0014');
  });
});
