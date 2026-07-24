import { Link, useLocation } from "react-router-dom";
import {
  buildProductNavigation,
  isProductNavigationActive,
} from "../lib/productNavigation.js";

function MenuLinks({ items, pathname }) {
  return items.map(item => {
    const active = isProductNavigationActive(item.key, pathname);
    const props = {
      className: active ? "is-active" : undefined,
      "aria-current": active ? "page" : undefined,
      onClick: event => {
        const details = event.currentTarget.closest("details");
        if (details) details.removeAttribute("open");
      },
    };
    return item.clientSide
      ? <Link key={item.key} to={item.href} {...props}>{item.label}</Link>
      : <a key={item.key} href={item.href} {...props}>{item.label}</a>;
  });
}

export function CitizenMenu({
  runId = "",
  worldSlug = "local-sandbox",
  navigation = null,
  variant = "header",
}) {
  const { pathname } = useLocation();
  const items = buildProductNavigation({ runId, worldSlug, navigation });

  if (variant === "dropdown") {
    return <details className="citizen-menu-dropdown">
      <summary>Citizen menu <span aria-hidden="true">⌄</span></summary>
      <nav className="citizen-menu citizen-menu--panel" aria-label="Agent Economy sections">
        <MenuLinks items={items} pathname={pathname} />
      </nav>
    </details>;
  }

  return <nav
    className={`citizen-menu citizen-menu--${variant}`}
    aria-label="Agent Economy sections"
  >
    <span className="citizen-menu__label">Explore</span>
    <MenuLinks items={items} pathname={pathname} />
  </nav>;
}
