const base = { width: 20, height: 20, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeWidth: 1.8, strokeLinecap: 'round', strokeLinejoin: 'round', 'aria-hidden': true };

const icon = (paths) => function Icon({ size = 20, ...props }) {
  return <svg {...base} width={size} height={size} {...props}>{paths}</svg>;
};

export const MenuIcon = icon(<><path d="M4 7h16" /><path d="M4 12h16" /><path d="M4 17h10" /></>);
export const PlusIcon = icon(<><path d="M12 5v14" /><path d="M5 12h14" /></>);
export const EditIcon = icon(<><path d="M12 20h9" /><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z" /></>);
export const PaperclipIcon = icon(<path d="m21 11-8.5 8.5a5 5 0 0 1-7-7L14 4a3.5 3.5 0 0 1 5 5l-8.6 8.6a2 2 0 0 1-2.8-2.8L15 7.5" />);
export const ArrowUpIcon = icon(<><path d="M12 19V5" /><path d="m5 12 7-7 7 7" /></>);
export const TrashIcon = icon(<><path d="M3 6h18" /><path d="M8 6V4h8v2" /><path d="m6 6 1 14h10l1-14" /></>);
export const CopyIcon = icon(<><rect x="9" y="9" width="11" height="11" rx="2" /><path d="M5 15V6a2 2 0 0 1 2-2h9" /></>);
export const CheckIcon = icon(<path d="m5 12 5 5L20 7" />);
export const SunIcon = icon(<><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" /></>);
export const MoonIcon = icon(<path d="M21 13A9 9 0 1 1 11 3a7 7 0 0 0 10 10Z" />);
export const FileIcon = icon(<><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8Z" /><path d="M14 3v5h5" /></>);
export const ChatIcon = icon(<path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12Z" />);
export const CloseIcon = icon(<><path d="M6 6l12 12" /><path d="M18 6 6 18" /></>);
export const CloudIcon = icon(<path d="M7 18a4 4 0 0 1-.6-8A6 6 0 0 1 18 9.5a4.2 4.2 0 0 1-.5 8.5Z" />);
export const SparkleIcon = icon(<path d="M12 3c.6 4.6 2.4 6.4 7 7-4.6.6-6.4 2.4-7 7-.6-4.6-2.4-6.4-7-7 4.6-.6 6.4-2.4 7-7Z" />);
export const ChartIcon = icon(<><path d="M4 20V10" /><path d="M10 20V4" /><path d="M16 20v-7" /><path d="M22 20H2" /></>);
export const SpinnerIcon = icon(<path d="M12 3a9 9 0 1 0 9 9" />);
