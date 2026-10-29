import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Link, Route, Routes } from "react-router-dom";

import { Layout } from "./components/Layout";
import { EmptyState } from "./components/States";
import { ClientDetailPage } from "./pages/ClientDetailPage";
import { ClientsDealsPage } from "./pages/ClientsDealsPage";
import { DashboardPage } from "./pages/DashboardPage";
import { DealDetailPage } from "./pages/DealDetailPage";
import { GraphExplorerPage } from "./pages/GraphExplorerPage";
import { HeatmapPage } from "./pages/HeatmapPage";
import { RepProfilePage } from "./pages/RepProfilePage";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { staleTime: 30_000, retry: 1, refetchOnWindowFocus: false },
  },
});

function NotFound() {
  return (
    <div className="p-6">
      <EmptyState title="Page not found">
        <Link to="/" className="link">
          Go to the dashboard
        </Link>
      </EmptyState>
    </div>
  );
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Layout>
          <Routes>
            <Route path="/" element={<DashboardPage />} />
            <Route path="/deals" element={<ClientsDealsPage />} />
            <Route path="/clients" element={<ClientsDealsPage />} />
            <Route path="/deals/:id" element={<DealDetailPage />} />
            <Route path="/clients/:id" element={<ClientDetailPage />} />
            <Route path="/reps/:id" element={<RepProfilePage />} />
            <Route path="/heatmap" element={<HeatmapPage />} />
            <Route path="/graph" element={<GraphExplorerPage />} />
            <Route path="*" element={<NotFound />} />
          </Routes>
        </Layout>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
