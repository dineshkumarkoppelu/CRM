// react-query hooks, one per endpoint. Query keys start with the resource so a mutation can
// invalidate exactly what it changed; admin actions invalidate everything.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./client";
import type {
  Activity,
  ActivityCreate,
  AppConfig,
  AssignmentResult,
  Backtest,
  Client,
  ClientCreateResult,
  ClientDetail,
  ClientWithDealCreate,
  DealDetail,
  DealFilters,
  Deal,
  DealStatus,
  Domain,
  DomainCreate,
  DomainInfo,
  DomainTrend,
  Forecast,
  Health,
  Heatmap,
  Kpis,
  Leaderboard,
  Page,
  Pipeline,
  RecomputeResult,
  SalesPerson,
  SalesPersonDetail,
  SalesPersonUpdate,
  SeedResult,
  SimilarityCompareRow,
  StageAction,
  StalledDeal,
  Subgraph,
} from "./types";

// ---- meta ----
export const useHealth = () =>
  useQuery({ queryKey: ["health"], queryFn: () => api.get<Health>("/health"), retry: false });
export const useConfig = () =>
  useQuery({ queryKey: ["meta", "config"], queryFn: () => api.get<AppConfig>("/meta/config"), staleTime: Infinity });
/** Domain names in display order (built-ins first). Not static any more: domains can be added. */
export const useDomains = () =>
  useQuery({ queryKey: ["domains", "names"], queryFn: () => api.get<Domain[]>("/meta/domains"), staleTime: 60_000 });
export const useDomainList = () =>
  useQuery({ queryKey: ["domains", "list"], queryFn: () => api.get<DomainInfo[]>("/domains") });

// ---- sales people ----
export const useSalesPeople = (active?: boolean) =>
  useQuery({
    queryKey: ["salespeople", { active }],
    queryFn: () => api.get<Page<SalesPerson>>("/salespeople", { active, limit: 200 }),
  });
export const useSalesPerson = (id: string | undefined) =>
  useQuery({
    queryKey: ["salespeople", id],
    queryFn: () => api.get<SalesPersonDetail>(`/salespeople/${id}`),
    enabled: Boolean(id),
  });

// ---- clients / deals ----
export const useClients = (q: string, limit = 50, offset = 0) =>
  useQuery({
    queryKey: ["clients", { q, limit, offset }],
    queryFn: () => api.get<Page<Client>>("/clients", { q, limit, offset }),
    placeholderData: (previous) => previous,
  });
export const useClient = (id: string | undefined) =>
  useQuery({
    queryKey: ["clients", id],
    queryFn: () => api.get<ClientDetail>(`/clients/${id}`),
    enabled: Boolean(id),
  });
export const useDeals = (filters: DealFilters) =>
  useQuery({
    queryKey: ["deals", filters],
    queryFn: () => api.get<Page<Deal>>("/deals", { ...filters }),
    placeholderData: (previous) => previous,
  });
export const useDeal = (id: string | undefined) =>
  useQuery({
    queryKey: ["deals", id],
    queryFn: () => api.get<DealDetail>(`/deals/${id}`),
    enabled: Boolean(id),
  });
export const useRecommendations = (dealId: string | undefined) =>
  useQuery({
    queryKey: ["recommendations", dealId],
    queryFn: () => api.get<AssignmentResult>(`/recommendations/${dealId}`),
    enabled: Boolean(dealId),
  });

// ---- analytics ----
export const useKpis = () => useQuery({ queryKey: ["analytics", "kpis"], queryFn: () => api.get<Kpis>("/analytics/kpis") });
export const usePipeline = () =>
  useQuery({ queryKey: ["analytics", "pipeline"], queryFn: () => api.get<Pipeline>("/analytics/pipeline") });
export const useHeatmap = () =>
  useQuery({ queryKey: ["analytics", "heatmap"], queryFn: () => api.get<Heatmap>("/analytics/heatmap") });
export const useStalled = () =>
  useQuery({ queryKey: ["analytics", "stalled"], queryFn: () => api.get<StalledDeal[]>("/analytics/stalled") });
export const useLeaderboard = () =>
  useQuery({ queryKey: ["analytics", "leaderboard"], queryFn: () => api.get<Leaderboard>("/analytics/leaderboard") });
export const useDomainTrend = () =>
  useQuery({ queryKey: ["analytics", "domain-trend"], queryFn: () => api.get<DomainTrend>("/analytics/domain-trend") });
export const useForecast = () =>
  useQuery({ queryKey: ["analytics", "forecast"], queryFn: () => api.get<Forecast>("/analytics/forecast") });
export const useBacktest = () =>
  useQuery({ queryKey: ["analytics", "backtest"], queryFn: () => api.get<Backtest>("/analytics/forecast/backtest") });
export const useSimilarityCompare = (enabled: boolean) =>
  useQuery({
    queryKey: ["analytics", "similarity-compare"],
    queryFn: () => api.get<SimilarityCompareRow[]>("/analytics/similarity-compare"),
    enabled,
    staleTime: 5 * 60_000,
  });

// ---- graph ----
export const useSubgraph = (repId: string | undefined, includePeers: boolean, dealStatus?: DealStatus) =>
  useQuery({
    queryKey: ["graph", repId, includePeers, dealStatus],
    queryFn: () =>
      api.get<Subgraph>("/graph/subgraph", {
        sales_person_id: repId,
        include_peers: includePeers,
        deal_status: dealStatus,
      }),
    enabled: Boolean(repId),
  });

// ---- mutations ----
/** Data that depends on deals / ownership / reps (everything except static meta). */
function invalidateBusinessData(qc: ReturnType<typeof useQueryClient>) {
  for (const key of ["deals", "clients", "salespeople", "analytics", "recommendations", "graph"]) {
    void qc.invalidateQueries({ queryKey: [key] });
  }
}

/** Adding a domain changes rep similarity and every per-domain view, so refresh everything. */
export function useCreateDomain() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: DomainCreate) => api.post<DomainInfo>("/domains", body),
    onSuccess: () => qc.invalidateQueries(),
  });
}

export function useCreateClientWithDeal() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: ClientWithDealCreate) => api.post<ClientCreateResult>("/clients", body),
    onSuccess: () => invalidateBusinessData(qc),
  });
}

export function useMoveStage() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ dealId, action }: { dealId: string; action: StageAction }) =>
      api.post<Deal>(`/deals/${dealId}/stage`, { action }),
    onSuccess: () => invalidateBusinessData(qc),
  });
}

export function useLogActivity() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: ActivityCreate) => api.post<Activity>("/activities", body),
    onSuccess: (_, body) => {
      void qc.invalidateQueries({ queryKey: ["deals", body.deal_id] });
      void qc.invalidateQueries({ queryKey: ["analytics", "stalled"] });
      void qc.invalidateQueries({ queryKey: ["analytics", "kpis"] });
    },
  });
}

export function useOverride() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ dealId, repId }: { dealId: string; repId: string }) =>
      api.post<AssignmentResult>(`/recommendations/${dealId}/override`, { sales_person_id: repId }),
    onSuccess: () => invalidateBusinessData(qc),
  });
}

export function usePreview() {
  return useMutation({
    mutationFn: (dealId: string) => api.post<AssignmentResult>(`/recommendations/${dealId}/preview`),
  });
}

export function useRunAssignment() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (dealId: string) => api.post<AssignmentResult>(`/recommendations/${dealId}/run`),
    onSuccess: () => invalidateBusinessData(qc),
  });
}

export function useUpdateSalesPerson() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, changes }: { id: string; changes: SalesPersonUpdate }) =>
      api.patch<SalesPerson>(`/salespeople/${id}`, changes),
    onSuccess: () => invalidateBusinessData(qc),
  });
}

export function useSeed() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.post<SeedResult>("/admin/seed"),
    onSuccess: () => qc.invalidateQueries(),
  });
}

export function useRecompute() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.post<RecomputeResult>("/admin/recompute"),
    onSuccess: () => qc.invalidateQueries(),
  });
}
