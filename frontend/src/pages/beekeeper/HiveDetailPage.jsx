import { useCallback, useEffect, useState } from 'react';
import { ArrowLeft, MapPin, Pencil, RefreshCw, Repeat } from 'lucide-react';
import { useParams } from 'react-router-dom';

import { Alert } from '@/components/ui/Alert';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card, CardBody, CardHeader } from '@/components/ui/Card';
import { Breadcrumb } from '@/components/common/Breadcrumb';
import { ErrorState } from '@/components/common/ErrorState';
import { LoadingState } from '@/components/common/LoadingState';
import { PageHeader } from '@/components/common/PageHeader';
import { StatusBadge } from '@/components/common/StatusBadge';
import { HiveFormModal } from '@/components/hives/HiveFormModal';
import { HiveStatusDialog } from '@/components/hives/HiveStatusDialog';
import { DeviceDetailPanel } from '@/components/iot/DeviceDetailPanel';
import { DevicePairingModal } from '@/components/iot/DevicePairingModal';
import { NoDevicePanel, SensorSnapshotGrid } from '@/components/iot/SensorSnapshotGrid';
import { TelemetryChart } from '@/components/iot/TelemetryChart';
import { HiveAiSection } from '@/components/ai/HiveAiSection';
import { HiveClusterControl } from '@/components/clusters/HiveClusterControl';
import { ROLES } from '@/constants/roles';
import { normaliseError } from '@/utils/errors';
import { formatDate, formatDateTime, titleCase } from '@/utils/format';
import { useAuth } from '@/hooks/useAuth';
import * as hiveService from '@/services/hiveService';

/** "16.3067, 80.4365" or nothing at all. */
function coordinateLabel(hive) {
  if (!hive.has_coordinates || hive.latitude === null || hive.longitude === null) return null;
  return `${Number(hive.latitude).toFixed(4)}, ${Number(hive.longitude).toFixed(4)}`;
}

function DetailItem({ label, children }) {
  return (
    <div className="border-b border-sand-200 py-2 last:border-b-0">
      <dt className="text-xs uppercase tracking-wide text-ink-muted">{label}</dt>
      <dd className="mt-0.5 text-sm text-ink">{children}</dd>
    </div>
  );
}

/**
 * One hive, in full: what was registered, which device reports on it, the last
 * values that device sent and the stored history.
 *
 * Every value on this page came from a stored row. Where nothing was recorded
 * the page says so ("not recorded", "no reading yet") rather than filling the
 * space with a plausible default.
 */
/**
 * Role-aware presentation.
 *
 * The API decides what each role may do; this only avoids offering a button
 * that would come back 403. KVIC officers inspect hives read-only, an
 * administrator may correct a record, and the owner may do everything.
 */
const HOME = {
  [ROLES.BEEKEEPER]: { label: 'My hives', to: '/beekeeper/hives' },
  [ROLES.KVIC_OFFICER]: { label: 'Hive registry', to: '/kvic/hives' },
  [ROLES.ADMIN]: { label: 'Hive registry', to: '/admin/hives' },
};

/** Where this role handles alerts — one record, three entry points. */
const ALERTS_HOME = {
  [ROLES.BEEKEEPER]: '/beekeeper/alerts',
  [ROLES.KVIC_OFFICER]: '/kvic/alerts',
  [ROLES.ADMIN]: '/admin/alerts',
};

export default function HiveDetailPage() {
  const { hiveId } = useParams();
  const { role } = useAuth();
  const home = HOME[role] || HOME[ROLES.BEEKEEPER];
  const canEdit = role === ROLES.BEEKEEPER || role === ROLES.ADMIN;
  // Placing a hive in a cluster is a KVIC/administrative decision — the API
  // refuses a beekeeper's request with 403 whether or not this panel is drawn.
  const canPlace = role === ROLES.KVIC_OFFICER || role === ROLES.ADMIN;
  const [hive, setHive] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [selectedDevice, setSelectedDevice] = useState(null);
  const [editOpen, setEditOpen] = useState(false);
  const [statusOpen, setStatusOpen] = useState(false);
  const [pairOpen, setPairOpen] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await hiveService.getHive(hiveId);
      setHive(data);
      setSelectedDevice((current) => current || data.devices?.[0]?.id || null);
    } catch (caught) {
      setError(normaliseError(caught));
      setHive(null);
    } finally {
      setLoading(false);
    }
  }, [hiveId]);

  useEffect(() => {
    load();
  }, [load]);

  if (loading) return <LoadingState message="Loading hive…" />;
  if (error) return <ErrorState error={error} onRetry={load} />;
  if (!hive) return null;

  const coordinates = coordinateLabel(hive);
  const hasDevices = (hive.devices || []).length > 0;

  return (
    <div className="space-y-5">
      <Breadcrumb items={[{ label: home.label, to: home.to }, { label: hive.hive_code }]} />

      <PageHeader
        title={hive.hive_code}
        badge={<StatusBadge status={hive.status} />}
        description={hive.location_label || 'No location recorded for this hive yet.'}
        actions={
          <>
            {canEdit ? (
              <>
                <Button
                  variant="secondary"
                  size="sm"
                  leftIcon={<Repeat size={15} aria-hidden="true" />}
                  onClick={() => setStatusOpen(true)}
                >
                  Change status
                </Button>
                <Button
                  variant="secondary"
                  size="sm"
                  leftIcon={<Pencil size={15} aria-hidden="true" />}
                  onClick={() => setEditOpen(true)}
                >
                  Edit
                </Button>
              </>
            ) : null}
            <Button variant="ghost" size="sm" onClick={load} leftIcon={<RefreshCw size={15} aria-hidden="true" />}>
              Refresh
            </Button>
          </>
        }
      />

      {hive.status === 'REMOVED' ? (
        <Alert variant="warning" title="This hive is retired">
          It was marked REMOVED, so no new readings are expected. Its history stays readable — that is
          why the record was kept instead of deleted.
        </Alert>
      ) : null}

      <div className="grid gap-5 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader
            title="Registration"
            description="Entered by you. The hive code was generated by the platform and never changes."
          />
          <CardBody>
            <dl className="grid gap-x-6 sm:grid-cols-2">
              <DetailItem label="Bee species">{hive.bee_species || 'Not recorded'}</DetailItem>
              <DetailItem label="Colony strength (your assessment)">
                {hive.colony_strength_label || titleCase(hive.colony_strength)}
              </DetailItem>
              <DetailItem label="Queen status (your observation)">
                {hive.queen_status_label || titleCase(hive.queen_status)}
              </DetailItem>
              <DetailItem label="Installed">
                {hive.installation_date ? formatDate(hive.installation_date) : 'Not recorded'}
              </DetailItem>
              <DetailItem label="Village / mandal">
                {[hive.village, hive.mandal].filter(Boolean).join(' · ') || 'Not recorded'}
              </DetailItem>
              <DetailItem label="District / state">
                {[hive.district, hive.state].filter(Boolean).join(', ') || 'Not recorded'}
              </DetailItem>
              <DetailItem label="PIN code">{hive.pincode || 'Not recorded'}</DetailItem>
              <DetailItem label="Coordinates">
                {coordinates ? (
                  <span className="flex items-center gap-1.5">
                    <MapPin size={14} aria-hidden="true" />
                    {coordinates}
                  </span>
                ) : (
                  'Not recorded'
                )}
              </DetailItem>
              <DetailItem label="Cluster">
                {hive.cluster ? `${hive.cluster.cluster_code} — ${hive.cluster.cluster_name}` : 'Not in a cluster'}
              </DetailItem>
              <DetailItem label="Registered">{formatDateTime(hive.created_at)}</DetailItem>
            </dl>

            {hive.notes ? (
              <div className="mt-4 rounded-lg bg-sand-100/60 p-3">
                <p className="text-xs uppercase tracking-wide text-ink-muted">Notes</p>
                <p className="mt-1 whitespace-pre-line text-sm text-ink-soft">{hive.notes}</p>
              </div>
            ) : null}
          </CardBody>
        </Card>

        <Card>
          <CardHeader
            title="Sensors"
            description={
              hasDevices
                ? `From ${hive.primary_device?.device_id}`
                : 'No device is paired with this hive yet'
            }
          />
          <CardBody>
            {hasDevices ? (
              <SensorSnapshotGrid sensors={hive.primary_device?.sensors || []} reading={hive.latest_reading} />
            ) : (
              <>
                <NoDevicePanel hiveCode={hive.hive_code} />
                {canEdit ? (
                  <Button className="mt-3" fullWidth onClick={() => setPairOpen(true)}>
                    Pair a device
                  </Button>
                ) : null}
              </>
            )}
          </CardBody>
        </Card>
      </div>

      {hasDevices ? (
        <>
          <Card>
            <CardHeader
              title="Devices on this hive"
              description="Status is derived from the last packet the platform received."
              action={
                canEdit ? (
                  <Button variant="secondary" size="sm" onClick={() => setPairOpen(true)}>
                    Pair another device
                  </Button>
                ) : null
              }
            />
            <CardBody>
              <div className="flex flex-wrap gap-2">
                {(hive.devices || []).map((device) => (
                  <button
                    key={device.id}
                    type="button"
                    onClick={() => setSelectedDevice(device.id)}
                    className={[
                      'rounded-lg border px-3 py-2 text-left transition-colors',
                      selectedDevice === device.id
                        ? 'border-honey-500 bg-honey-50'
                        : 'border-sand-300 bg-white hover:bg-sand-100',
                    ].join(' ')}
                  >
                    <span className="block text-sm font-medium text-ink">{device.device_id}</span>
                    <span className="mt-0.5 flex items-center gap-1.5">
                      <StatusBadge status={device.status} size="sm" />
                      <Badge variant="neutral" size="sm">
                        {device.sensors?.length ?? 0} sensors
                      </Badge>
                    </span>
                  </button>
                ))}
              </div>
            </CardBody>
          </Card>

          {selectedDevice ? (
            <section className="rounded-card border border-sand-300 bg-white p-4 shadow-card">
              <DeviceDetailPanel deviceId={selectedDevice} canEdit={canEdit} onChanged={load} />
            </section>
          ) : null}
        </>
      ) : null}

      {/*
        Cluster placement. Read-only for the hive's owner — a hive inherits its
        owner's cluster — and an explicit, audited action for staff.
      */}
      {canPlace ? (
        <HiveClusterControl hive={hive} onChanged={(updated) => setHive(updated)} />
      ) : null}

      <TelemetryChart
        hiveId={hive.id}
        hiveCode={hive.hive_code}
        defaultDeviceId={hive.primary_device?.device_id}
      />

      {/*
        AI insights for this hive. The same component serves every role that can
        open the page; what it may show is decided by the API, and every figure
        on it is a stored analysis rather than anything computed here.
      */}
      <HiveAiSection
        hiveId={hive.id}
        hiveCode={hive.hive_code}
        alertsHref={ALERTS_HOME[role] || ALERTS_HOME[ROLES.BEEKEEPER]}
      />

      <Button variant="ghost" to={home.to} leftIcon={<ArrowLeft size={15} aria-hidden="true" />}>
        Back to {home.label.toLowerCase()}
      </Button>

      <HiveFormModal open={editOpen} hive={hive} onClose={() => setEditOpen(false)} onSaved={load} />
      <HiveStatusDialog open={statusOpen} hive={hive} onClose={() => setStatusOpen(false)} onSaved={load} />
      <DevicePairingModal
        open={pairOpen}
        hives={[hive]}
        defaultHiveId={hive.id}
        onClose={() => setPairOpen(false)}
        onSaved={load}
      />
    </div>
  );
}
