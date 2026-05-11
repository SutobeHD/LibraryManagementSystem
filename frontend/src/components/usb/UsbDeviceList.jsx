/**
 * UsbDeviceList — left rail of the USB view.
 *
 * Renders the list of registered + connected USB drives. Selection state
 * is owned by the parent container (UsbView) and passed in via props.
 */
import React from 'react';
import {
    HardDrive, Usb, AlertTriangle, Loader2, Clock,
} from 'lucide-react';
import { FS_COMPAT, normalizeFs, worstCdjStatus, formatDate } from './UsbControls';

const UsbDeviceList = ({
    devices,
    allDevices,
    selectedDeviceId,
    scanning,
    syncing,
    hiddenCount,
    isConnected,
    onSelect,
}) => {
    const sel = allDevices.find(d => d.device_id === selectedDeviceId);

    return (
        <div className="w-72 border-r border-line-subtle overflow-y-auto p-2 space-y-1 bg-mx-shell">
            <div className="mx-caption px-3 py-2">Devices</div>

            {allDevices.length === 0 && !scanning && (
                <div className="flex flex-col items-center justify-center h-48 text-center px-4">
                    <Usb size={32} className="text-ink-placeholder mb-3" />
                    <p className="text-[12px] text-ink-muted">No USB devices detected</p>
                    <p className="text-[10px] text-ink-placeholder mt-1">Insert a USB stick and click Scan</p>
                    {hiddenCount > 0 && (
                        <p className="text-[10px] text-ink-placeholder mt-2">{hiddenCount} system drive(s) hidden</p>
                    )}
                </div>
            )}
            {scanning && allDevices.length === 0 && (
                <div className="flex items-center justify-center h-32">
                    <Loader2 size={20} className="animate-spin text-amber2" />
                </div>
            )}

            {allDevices.map(device => {
                const connected = isConnected(device);
                const isSelected = sel?.device_id === device.device_id;
                const fsKey = normalizeFs(device.filesystem);
                const compat = FS_COMPAT[fsKey] || FS_COMPAT.UNKNOWN;
                const worst = worstCdjStatus(compat);
                return (
                    <button
                        key={device.device_id}
                        onClick={() => onSelect(device.device_id)}
                        className={`w-full text-left p-2.5 rounded-mx-sm border transition-all ${
                            isSelected
                                ? 'bg-mx-selected border-amber2/50'
                                : 'bg-mx-card border-line-subtle hover:bg-mx-hover hover:border-line-default'
                        }`}
                    >
                        <div className="flex items-center gap-2.5">
                            <div className={`w-1.5 h-1.5 rounded-full shrink-0 ${
                                connected ? 'bg-ok shadow-[0_0_4px_#3DD68C]' : 'bg-ink-placeholder'
                            }`} />
                            <HardDrive size={14} className={isSelected ? 'text-amber2' : 'text-ink-secondary'} />
                            <div className="flex-1 min-w-0">
                                <div className="text-[13px] font-medium text-ink-primary truncate">
                                    {device.label || 'USB Drive'}
                                </div>
                                <div className="text-[11px] font-mono flex items-center gap-1.5 mt-0.5">
                                    <span className="text-ink-primary font-semibold">{device.drive}</span>
                                    <span className="text-ink-placeholder">·</span>
                                    <span className="text-amber2">{fsKey}</span>
                                    <span className="text-ink-placeholder">·</span>
                                    <span className="text-ink-secondary">{device.track_count || 0} tracks</span>
                                </div>
                            </div>
                            {/* Compat status badge */}
                            {worst === 'partial' && (
                                <AlertTriangle size={12} className="text-orange-500 shrink-0" title="Wrong format for CDJs — consider reformatting" />
                            )}
                            {worst === 'warn' && (
                                <AlertTriangle size={12} className="text-amber2 shrink-0" title="Limited CDJ support" />
                            )}
                            {syncing === device.device_id && (
                                <Loader2 size={12} className="animate-spin text-amber2 shrink-0" />
                            )}
                        </div>
                        {device.last_sync && (
                            <div className="mt-1.5 ml-5 text-[10px] text-ink-placeholder font-mono flex items-center gap-1">
                                <Clock size={9} /> {formatDate(device.last_sync)}
                            </div>
                        )}
                    </button>
                );
            })}
        </div>
    );
};

export default UsbDeviceList;
