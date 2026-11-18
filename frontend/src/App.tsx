import { useEffect } from "react";
import { Navigate, Outlet, Route, Routes, useNavigate } from "react-router";
import { isSignedIn, setUnauthenticatedHandler } from "./api/client";
import { ForecastsPage } from "./brain/ForecastsPage";
import { RiskPage } from "./brain/RiskPage";
import { InventoryPage } from "./erp/InventoryPage";
import { LoginPage } from "./erp/LoginPage";
import { ProductsPage } from "./erp/ProductsPage";
import { PurchaseOrdersPage } from "./erp/PurchaseOrdersPage";
import { SuppliersPage } from "./erp/SuppliersPage";
import { SalesPage } from "./erp/sales/SalesPage";
import { AppLayout } from "./layout/AppLayout";

/** Every route except /login needs a token; any 401 sends the manager back to /login (FR-002). */
function RequireAuth() {
  const navigate = useNavigate();
  useEffect(() => {
    setUnauthenticatedHandler(() => navigate("/login", { replace: true }));
    return () => setUnauthenticatedHandler(null);
  }, [navigate]);
  return isSignedIn() ? <Outlet /> : <Navigate to="/login" replace />;
}

export function AppRoutes() {
  return (
    <Routes>
      <Route element={<AppLayout />}>
        <Route path="/login" element={<LoginPage />} />
        <Route element={<RequireAuth />}>
          <Route path="/products" element={<ProductsPage />} />
          <Route path="/suppliers" element={<SuppliersPage />} />
          <Route path="/inventory" element={<InventoryPage />} />
          <Route path="/sales" element={<SalesPage />} />
          <Route path="/purchase-orders" element={<PurchaseOrdersPage />} />
          <Route path="/brain/risk" element={<RiskPage />} />
          <Route path="/brain/forecasts" element={<ForecastsPage />} />
        </Route>
        <Route path="*" element={<Navigate to="/products" replace />} />
      </Route>
    </Routes>
  );
}
