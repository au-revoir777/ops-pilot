import { FlaskConical, History, LayoutDashboard, Network, Search, type LucideIcon } from "lucide-react";

export type NavItem = { href: string; label: string; icon: LucideIcon; shortcut: string };

export const NAV: NavItem[] = [
  { href: "/", label: "Dashboard", icon: LayoutDashboard, shortcut: "g d" },
  { href: "/investigations", label: "Investigations", icon: Search, shortcut: "g i" },
  { href: "/incident-lab", label: "Incident Lab", icon: FlaskConical, shortcut: "g l" },
  { href: "/history", label: "Incident History", icon: History, shortcut: "g h" },
  { href: "/system", label: "System Status", icon: Network, shortcut: "g s" },
];

export function isActive(pathname: string, href: string) {
  return href === "/" ? pathname === "/" : pathname === href || pathname.startsWith(`${href}/`);
}
