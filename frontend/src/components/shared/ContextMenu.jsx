import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import ReactDOM from 'react-dom';

// App-wide right-click menu. Every surface that reacts to a right-click renders
// this instead of letting the WebView show its browser menu (Reload / Inspect /
// Save image… never make sense inside the app).
//
// item shape:
//   { id, label, icon: LucideIcon, onSelect, disabled, danger, hint, separator: true }

const MENU_MARGIN = 8;

const ContextMenuItem = ({ item, onClose }) => {
    if (item.separator) return <div className="h-px bg-line-subtle my-1" />;
    const Icon = item.icon;
    return (
        <button
            type="button"
            disabled={item.disabled}
            onClick={() => {
                if (item.disabled) return;
                onClose();
                item.onSelect?.();
            }}
            className={`w-full flex items-center gap-3 px-4 py-2 text-[12px] text-left transition-colors disabled:opacity-30 disabled:cursor-default hover:bg-mx-hover ${
                item.danger
                    ? 'text-ink-secondary hover:text-red-400'
                    : 'text-ink-secondary hover:text-amber2'
            }`}
        >
            {Icon ? <Icon size={14} /> : <span className="w-[14px]" />}
            <span className="flex-1 truncate">{item.label}</span>
            {item.hint && <span className="mx-caption shrink-0">{item.hint}</span>}
        </button>
    );
};

export const ContextMenu = ({ x, y, items, header, onClose }) => {
    const ref = useRef(null);
    const [pos, setPos] = useState({ top: y, left: x });

    // Clamp into the viewport once the real size is known — a menu opened near
    // the bottom/right edge would otherwise render half off-screen.
    useLayoutEffect(() => {
        const el = ref.current;
        if (!el) return;
        const { width, height } = el.getBoundingClientRect();
        const left = Math.max(MENU_MARGIN, Math.min(x, window.innerWidth - width - MENU_MARGIN));
        const top = Math.max(MENU_MARGIN, Math.min(y, window.innerHeight - height - MENU_MARGIN));
        setPos({ top, left });
    }, [x, y, items]);

    useEffect(() => {
        const onKey = (e) => {
            if (e.key === 'Escape') onClose();
        };
        const onDown = (e) => {
            if (!ref.current?.contains(e.target)) onClose();
        };
        const onScroll = () => onClose();
        window.addEventListener('keydown', onKey);
        window.addEventListener('mousedown', onDown, true);
        window.addEventListener('blur', onClose);
        window.addEventListener('resize', onClose);
        document.addEventListener('scroll', onScroll, true);
        return () => {
            window.removeEventListener('keydown', onKey);
            window.removeEventListener('mousedown', onDown, true);
            window.removeEventListener('blur', onClose);
            window.removeEventListener('resize', onClose);
            document.removeEventListener('scroll', onScroll, true);
        };
    }, [onClose]);

    const visible = (items || []).filter(Boolean);
    if (!visible.length) return null;

    return ReactDOM.createPortal(
        <div
            ref={ref}
            data-context-menu="true"
            role="menu"
            className="fixed z-[200] bg-mx-panel border border-line-default rounded-mx-md shadow-mx-lg min-w-[220px] max-w-[320px] py-1 animate-fade-in"
            style={{ top: pos.top, left: pos.left }}
            onContextMenu={(e) => e.preventDefault()}
        >
            {header && (
                <div className="mx-caption px-3 py-2 border-b border-line-subtle truncate">
                    {header}
                </div>
            )}
            {visible.map((item, i) => (
                <ContextMenuItem key={item.id || `sep-${i}`} item={item} onClose={onClose} />
            ))}
        </div>,
        document.body
    );
};

/**
 * State holder for a single context menu per component.
 *
 *   const ctx = useContextMenu();
 *   <tr onContextMenu={(e) => ctx.open(e, buildItems(row), row.name)} />
 *   {ctx.node}
 */
export function useContextMenu() {
    const [state, setState] = useState(null);
    const close = useCallback(() => setState(null), []);
    const open = useCallback((e, items, header) => {
        e.preventDefault();
        e.stopPropagation();
        const visible = (items || []).filter(Boolean);
        if (!visible.length) return;
        setState({ x: e.clientX, y: e.clientY, items: visible, header });
    }, []);

    const node = state ? (
        <ContextMenu
            x={state.x}
            y={state.y}
            items={state.items}
            header={state.header}
            onClose={close}
        />
    ) : null;

    return { open, close, node, isOpen: !!state };
}

export default ContextMenu;
