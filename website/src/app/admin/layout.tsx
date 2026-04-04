import type { ReactNode } from "react";
import AdminSidebar from "@/components/admin/AdminSidebar";
import AdminAuthGate from "@/components/admin/AdminAuthGate";

export const metadata = {
  title: "Admin | Livestream to AGI",
};

export default function AdminLayout({ children }: { children: ReactNode }) {
  return (
    <AdminAuthGate>
      <div className="flex min-h-screen bg-background">
        <AdminSidebar />
        <div className="flex-1 overflow-auto p-6">{children}</div>
      </div>
    </AdminAuthGate>
  );
}
