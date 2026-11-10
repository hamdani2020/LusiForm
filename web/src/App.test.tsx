import { render, screen } from "@testing-library/react";

import App from "./App";

describe("App", () => {
  it("renders the Lusiform heading and primary action", () => {
    render(<App />);
    expect(screen.getByRole("heading", { name: "Lusiform" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Get started" })).toBeInTheDocument();
  });
});
