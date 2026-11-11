import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  ACCESS,
  REFRESH,
  config,
  fakeFetch,
  json,
  makeClient,
  meFor,
  renderApp,
  signInThroughCallback,
  clickSignIn,
} from "@/test/helpers";

beforeEach(() => {
  window.sessionStorage.clear();
  window.localStorage.clear();
  window.history.pushState(null, "", "/");
});

describe("unauthenticated visit", () => {
  it("shows the public landing page and does not redirect on its own", () => {
    const { fn, calls } = fakeFetch();
    const { redirect } = renderApp(makeClient(fn));

    expect(
      screen.getByRole("heading", { name: "From requirements to a validated Terraform project" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Access is by invitation from your partner admin.")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Sign in" })).toHaveLength(2);
    expect(redirect).not.toHaveBeenCalled();
    expect(calls).toHaveLength(0);
    // Signed-out visitors see no app content.
    expect(screen.queryByRole("navigation", { name: "Main" })).not.toBeInTheDocument();
  });

  it("lists the eight stages in order with their product names", () => {
    const { fn } = fakeFetch();
    renderApp(makeClient(fn));
    const stages = within(screen.getByRole("region", { name: "How a project moves" }))
      .getAllByRole("listitem")
      .map((li) => li.querySelector("span + span")?.textContent);
    expect(stages).toEqual([
      "Intake",
      "Architecture",
      "Diagram",
      "Estimate",
      "Terraform",
      "Validation",
      "Sandbox",
      "Handoff",
    ]);
  });

  it("makes no sign-up, SSO, pricing, uptime or compliance claim", () => {
    const { fn } = fakeFetch();
    const { container } = renderApp(makeClient(fn));
    const text = container.textContent ?? "";
    for (const banned of [
      /sign up/i,
      /get started/i,
      /request a demo/i,
      /google|microsoft|sso|saml/i,
      /\$\d|per month|\/mo\b/i, // no price figures (the "AWS Pricing API" mention is fine)
      /uptime|sla\b/i,
      /soc ?2|iso ?27001|hipaa|pci|fedramp|gdpr/i,
      /claude/i,
      /\b20\d\d\b/, // no copyright year
    ]) {
      expect(text).not.toMatch(banned);
    }
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument(); // no email field
  });

  it("'Sign in' redirects to the Cognito hosted login with PKCE", async () => {
    const { fn } = fakeFetch();
    const { redirect } = renderApp(makeClient(fn));
    clickSignIn();

    await waitFor(() => expect(redirect).toHaveBeenCalledTimes(1));
    const url = new URL(redirect.mock.calls[0][0] as string);
    expect(`${url.origin}${url.pathname}`).toBe(`${config.domain}/oauth2/authorize`);
    expect(url.searchParams.get("response_type")).toBe("code");
    expect(url.searchParams.get("client_id")).toBe(config.clientId);
    expect(url.searchParams.get("redirect_uri")).toBe(config.redirectUri);
    expect(url.searchParams.get("code_challenge_method")).toBe("S256");
    expect(url.searchParams.get("code_challenge")).toMatch(/^[A-Za-z0-9_-]{43}$/);
    expect(url.searchParams.get("state")).toBeTruthy();
  });

  it("in production builds, explains sign-in is not configured and disables 'Sign in'", () => {
    const { redirect } = renderApp(null, vi.fn(), undefined, false);
    expect(screen.getByRole("alert")).toHaveTextContent("Sign-in is not configured");
    expect(screen.getByRole("alert")).not.toHaveTextContent(/preview/i);
    for (const button of screen.getAllByRole("button", { name: "Sign in" })) {
      expect(button).toBeDisabled();
    }
    expect(redirect).not.toHaveBeenCalled();
  });

  it("in development, 'Sign in' opens the Sign In design preview, which sends nothing", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    const { redirect } = renderApp(null, vi.fn(), undefined, true);
    expect(screen.getByRole("alert")).toHaveTextContent(/preview of the sign-in page/i);

    clickSignIn();
    expect(await screen.findByRole("heading", { name: "Sign In" })).toBeInTheDocument();
    expect(screen.getByRole("note")).toHaveTextContent(/design preview/i);
    expect(screen.getByText("Access is by invitation from your partner admin.")).toBeInTheDocument();

    const email = screen.getByLabelText("Email address");
    const password = screen.getByLabelText("Password");
    await userEvent.type(email, "casey@example.com");
    await userEvent.type(password, "hunter2");
    expect(email).not.toHaveAttribute("name");
    expect(password).not.toHaveAttribute("name");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));

    expect(screen.getByRole("status")).toHaveTextContent(/nothing was sent/i);
    expect(email).toHaveValue(""); // cleared on submit
    expect(password).toHaveValue("");
    expect(fetchSpy).not.toHaveBeenCalled();
    expect(redirect).not.toHaveBeenCalled();
    expect(JSON.stringify({ ...window.sessionStorage, ...window.localStorage })).not.toContain(
      "hunter2",
    );

    await userEvent.click(screen.getByRole("button", { name: "Back" }));
    expect(
      await screen.findByRole("heading", { name: "From requirements to a validated Terraform project" }),
    ).toBeInTheDocument();
    fetchSpy.mockRestore();
  });
});

describe("callback and token handling", () => {
  it("exchanges the code with the stored PKCE verifier and renders the shell", async () => {
    const { fn, calls } = fakeFetch();
    const { authorizeUrl } = await signInThroughCallback(fn);

    expect(await screen.findByRole("navigation", { name: "Main" })).toBeInTheDocument();

    const tokenCall = calls.find((c) => c.url.endsWith("/oauth2/token"));
    expect(tokenCall?.url).toBe(`${config.domain}/oauth2/token`);
    const body = new URLSearchParams(String(tokenCall?.init?.body));
    expect(body.get("grant_type")).toBe("authorization_code");
    expect(body.get("code")).toBe("the-code");
    expect(body.get("client_id")).toBe(config.clientId);
    expect(body.get("redirect_uri")).toBe(config.redirectUri);
    expect(body.get("client_secret")).toBeNull(); // public client
    // The verifier really belongs to the challenge that was sent to the hosted login.
    const verifier = body.get("code_verifier") ?? "";
    const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier));
    const challenge = btoa(String.fromCharCode(...new Uint8Array(digest)))
      .replace(/\+/g, "-")
      .replace(/\//g, "_")
      .replace(/=+$/, "");
    expect(challenge).toBe(authorizeUrl.searchParams.get("code_challenge"));
  });

  it("removes the code and state from the address bar", async () => {
    const { fn } = fakeFetch();
    await signInThroughCallback(fn);
    await screen.findByRole("navigation", { name: "Main" });
    expect(window.location.pathname).toBe("/");
    expect(window.location.search).toBe("");
  });

  it("sends the access token as a Bearer header on API calls", async () => {
    const { fn, calls } = fakeFetch();
    await signInThroughCallback(fn);
    await screen.findByRole("navigation", { name: "Main" });

    const meCall = calls.find((c) => c.url.endsWith("/api/me"));
    expect((meCall?.init?.headers as Record<string, string>).Authorization).toBe(`Bearer ${ACCESS}`);
  });

  it("stores no token or long-lived secret in the browser", async () => {
    const { fn } = fakeFetch();
    await signInThroughCallback(fn);
    await screen.findByRole("navigation", { name: "Main" });

    const dump = JSON.stringify({ ...window.localStorage }) + JSON.stringify({ ...window.sessionStorage });
    expect(dump).not.toContain(ACCESS);
    expect(dump).not.toContain(REFRESH);
    expect(window.localStorage.length).toBe(0);
    expect(window.sessionStorage.length).toBe(0); // PKCE values are removed after the callback
    expect(document.cookie).toBe("");
  });

  it("rejects a callback whose state does not match and never exchanges the code", async () => {
    const { fn, calls } = fakeFetch();
    window.history.pushState(null, "", "/");
    const first = renderApp(makeClient(fn));
    clickSignIn();
    await waitFor(() => expect(first.redirect).toHaveBeenCalled());
    first.unmount();

    window.history.pushState(null, "", "/auth/callback?code=the-code&state=forged");
    renderApp(makeClient(fn));

    expect(await screen.findByRole("alert")).toHaveTextContent(/did not match/i);
    expect(screen.getAllByRole("button", { name: "Sign in" })[0]).toBeEnabled(); // can retry
    expect(calls.some((c) => c.url.endsWith("/oauth2/token"))).toBe(false);
    expect(calls.some((c) => c.url.endsWith("/api/me"))).toBe(false);
  });

  it("shows an error when the hosted login returns one", async () => {
    window.history.pushState(null, "", "/auth/callback?error=access_denied");
    const { fn } = fakeFetch();
    renderApp(makeClient(fn));
    expect(await screen.findByRole("alert")).toHaveTextContent(/access_denied/);
  });

  it("shows an error when the token exchange fails", async () => {
    const { fn } = fakeFetch({ token: () => json({ error: "invalid_grant" }, 400) });
    await signInThroughCallback(fn);
    expect(await screen.findByRole("alert")).toHaveTextContent(/could not complete sign-in/i);
    expect(screen.queryByRole("navigation")).not.toBeInTheDocument();
  });
});

describe("authenticated shell", () => {
  it("shows the brand, Projects navigation, and the user's name and role", async () => {
    const { fn } = fakeFetch({ me: () => json(meFor({ roles: ["consultant"] })) });
    await signInThroughCallback(fn);

    const nav = await screen.findByRole("navigation", { name: "Main" });
    expect(screen.getAllByText("Lusiform").length).toBeGreaterThan(0);
    expect(screen.getByTestId("partner-name")).toHaveTextContent("Acme Cloud Solutions");
    expect(within(screen.getByRole("navigation", { name: "Breadcrumb" })).getByText("Projects"))
      .toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("heading", { name: "Projects", level: 1 })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "No projects yet" })).toBeInTheDocument();
    expect(within(nav).getByRole("link", { name: "Projects" })).toBeInTheDocument();
    expect(screen.getByTestId("user-name")).toHaveTextContent("Casey Consultant");
    expect(screen.getByTestId("user-role")).toHaveTextContent("Consultant");
    expect(screen.queryByText(/workspace/i)).not.toBeInTheDocument(); // no workspace picker
  });

  it("falls back to the email when there is no display name", async () => {
    const { fn } = fakeFetch({ me: () => json(meFor({ display_name: null })) });
    await signInThroughCallback(fn);
    expect(await screen.findByTestId("user-name")).toHaveTextContent("casey@example.com");
  });

  it("hides admin navigation from consultants", async () => {
    const { fn } = fakeFetch({ me: () => json(meFor({ roles: ["consultant"] })) });
    await signInThroughCallback(fn);
    await screen.findByRole("navigation", { name: "Main" });

    expect(screen.queryByText("Administration")).not.toBeInTheDocument();
    for (const label of ["Users & Roles", "Sandbox Accounts", "Default Assumptions", "Partners", "Audit Log"]) {
      expect(screen.queryByText(label)).not.toBeInTheDocument();
    }
  });

  it("shows the partner admin entries, and not the operator-only ones", async () => {
    const { fn } = fakeFetch({ me: () => json(meFor({ roles: ["partner_admin"] })) });
    await signInThroughCallback(fn);

    const admin = await screen.findByRole("list", { name: "Administration" });
    expect(within(admin).getAllByRole("button").map((b) => b.textContent)).toEqual([
      "Users & Roles",
      "Sandbox Accounts",
      "Default Assumptions",
    ]);
    expect(screen.queryByText("Template Versions")).not.toBeInTheDocument();
    expect(screen.queryByText("Audit Log")).not.toBeInTheDocument();
    expect(screen.getByTestId("user-role")).toHaveTextContent("Partner admin");
  });

  it("shows the operator entries to platform operators", async () => {
    const { fn } = fakeFetch({ me: () => json(meFor({ roles: ["platform_operator"] })) });
    await signInThroughCallback(fn);

    const admin = await screen.findByRole("list", { name: "Administration" });
    expect(within(admin).getAllByRole("button").map((b) => b.textContent)).toEqual([
      "Partners",
      "Template Versions",
      "Default Assumptions",
      "Audit Log",
    ]);
    expect(screen.queryByText("Users & Roles")).not.toBeInTheDocument();
  });

  it("explains a 403 from the API (inactive user or suspended partner)", async () => {
    const { fn } = fakeFetch({ me: () => json({ detail: "Forbidden" }, 403) });
    await signInThroughCallback(fn);

    expect(await screen.findByRole("alert")).toHaveTextContent(/not active|suspended/i);
    expect(screen.queryByRole("navigation", { name: "Main" })).not.toBeInTheDocument();
  });

  it("refreshes the token once on a 401 and retries", async () => {
    let meCalls = 0;
    const { fn, calls } = fakeFetch({
      me: () => (++meCalls === 1 ? json({ detail: "Not authenticated" }, 401) : json(meFor())),
      token: ({ init }) => {
        const grant = new URLSearchParams(String(init?.body)).get("grant_type");
        return grant === "refresh_token"
          ? json({ access_token: "access-token-2", expires_in: 3600 })
          : json({ access_token: ACCESS, refresh_token: REFRESH, expires_in: 3600 });
      },
    });
    await signInThroughCallback(fn);

    expect(await screen.findByRole("navigation", { name: "Main" })).toBeInTheDocument();
    const meHeaders = calls
      .filter((c) => c.url.endsWith("/api/me"))
      .map((c) => (c.init?.headers as Record<string, string>).Authorization);
    expect(meHeaders).toEqual([`Bearer ${ACCESS}`, "Bearer access-token-2"]);
    const refreshBody = new URLSearchParams(
      String(calls.filter((c) => c.url.endsWith("/oauth2/token")).at(-1)?.init?.body),
    );
    expect(refreshBody.get("grant_type")).toBe("refresh_token");
    expect(refreshBody.get("refresh_token")).toBe(REFRESH);
  });

  it("starts a new sign-in when the session cannot be refreshed", async () => {
    const { fn } = fakeFetch({
      me: () => json({ detail: "Not authenticated" }, 401),
      token: ({ init }) =>
        new URLSearchParams(String(init?.body)).get("grant_type") === "refresh_token"
          ? json({ error: "invalid_grant" }, 400)
          : json({ access_token: ACCESS, refresh_token: REFRESH, expires_in: 3600 }),
    });
    const { redirect } = await signInThroughCallback(fn);

    await waitFor(() => expect(redirect).toHaveBeenCalled());
    expect(String(redirect.mock.calls.at(-1)?.[0])).toContain("/oauth2/authorize");
  });

  it("signs out through the hosted logout endpoint", async () => {
    const { fn } = fakeFetch();
    const { redirect } = await signInThroughCallback(fn);
    await screen.findByRole("navigation", { name: "Main" });

    await userEvent.click(screen.getByRole("button", { name: /sign out/i }));
    const url = new URL(String(redirect.mock.calls.at(-1)?.[0]));
    expect(`${url.origin}${url.pathname}`).toBe(`${config.domain}/logout`);
    expect(url.searchParams.get("client_id")).toBe(config.clientId);
    expect(url.searchParams.get("logout_uri")).toBe(config.logoutUri);
  });
});
