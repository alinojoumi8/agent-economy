import { Link, useInRouterContext, useLocation } from "react-router";
import {
  buildProductNavigation,
  isProductNavigationActive,
} from "../lib/productNavigation.js";

function MenuLinks({ items, pathname, routerReady }) {
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
    return item.clientSide && routerReady
      ? <Link key={item.key} to={item.href} {...props}>{item.label}</Link>
      : <a key={item.key} href={item.href} {...props}>{item.label}</a>;
  });
}

function CitizenMenuContent({
  runId = "",
  worldSlug = "local-sandbox",
  navigation = null,
  variant = "header",
  pathname = "/",
  routerReady = false,
}) {
  const items = buildProductNavigation({ runId, worldSlug, navigation });

  if (variant === "dropdown") {
    return <details className="citizen-menu-dropdown">
      <summary>Citizen menu <span aria-hidden="true">⌄</span></summary>
      <nav className="citizen-menu citizen-menu--panel" aria-label="Agent Economy sections">
        <MenuLinks items={items} pathname={pathname} routerReady={routerReady} />
      </nav>
    </details>;
  }

  return <nav
    className={`citizen-menu citizen-menu--${variant}`}
    aria-label="Agent Economy sections"
  >
    <span className="citizen-menu__label">Explore</span>
    <MenuLinks items={items} pathname={pathname} routerReady={routerReady} />
  </nav>;
}

function RoutedCitizenMenu(props) {
  const { pathname } = useLocation();
  return <CitizenMenuContent {...props} pathname={pathname} routerReady />;
}

export function CitizenMenu(props) {
  const inRouter = useInRouterContext();
  return inRouter
    ? <RoutedCitizenMenu {...props} />
    : <CitizenMenuContent {...props} />;
}
