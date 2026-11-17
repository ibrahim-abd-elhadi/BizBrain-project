import { NavLink, Outlet, useLocation, useNavigate } from "react-router";
import { isSignedIn, logout } from "../api/client";
import "./app.css";

const LINKS = [
  ["/products", "Products"],
  ["/suppliers", "Suppliers"],
  ["/inventory", "Inventory"],
  ["/sales", "Sales"],
  ["/purchase-orders", "Purchase orders"],
] as const;

/** Wraps every route, login included, so the "Synthetic data" banner is on every screen (FR-027). */
export function AppLayout() {
  const navigate = useNavigate();
  useLocation(); // re-render on navigation so the menu follows the sign-in state
  const signedIn = isSignedIn();

  function signOut() {
    logout();
    navigate("/login");
  }

  return (
    <div className="app">
      <div role="note" data-testid="synthetic-banner" className="synthetic-banner">
        Synthetic data
      </div>
      <header className="app-header">
        <strong>BizBrain ERP</strong>
        {signedIn && (
          <nav aria-label="Main">
            {LINKS.map(([to, label]) => (
              <NavLink key={to} to={to}>
                {label}
              </NavLink>
            ))}
            <button type="button" onClick={signOut}>
              Sign out
            </button>
          </nav>
        )}
      </header>
      <main>
        <Outlet />
      </main>
    </div>
  );
}
