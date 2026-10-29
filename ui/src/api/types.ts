// TypeScript mirror of .kiro/steering/api-contracts.md. Dates are ISO strings ("YYYY-MM-DD").

/** A domain name: the 5 built-ins (AI, Cybersecurity, IoT, DevOps, Cloud Migration) plus any
 *  added at runtime via POST /api/domains. */
export type Domain = string;
export type DealStatus = "OPEN" | "WON" | "LOST";
export type Stage = "LEAD" | "QUALIFIED" | "PROPOSAL" | "NEGOTIATION";
export type StageAction = "ADVANCE" | "WIN" | "LOSE";
export type ActivityType = "CALL" | "EMAIL" | "MEETING" | "DEMO";
export type Outcome = "POSITIVE" | "NEUTRAL" | "NEGATIVE";
export type ClientSize = "SMB" | "MID_MARKET" | "ENTERPRISE";
export type Region = "North" | "South" | "East" | "West" | "International";
export type FitType = "DIRECT" | "PEER" | "RELATED" | "COLD_START";
export type RecommendationStatus = "ASSIGNED" | "CANDIDATE" | "OVERRIDDEN";
export type AssignmentStatus = "ASSIGNED" | "UNASSIGNED" | "MANUAL" | "PENDING_ENGINE";
export type ProbabilitySource = "REP_DOMAIN_STAGE" | "TEAM_DOMAIN_STAGE" | "TEAM_STAGE";

export interface Page<T> {
  items: T[];
  total: number;
}

export interface ApiErrorBody {
  error: { code: string; message: string; details: Record<string, unknown> };
}

// ---- health / meta / admin ----
export interface Health {
  status: "ok" | "degraded";
  neo4j: {
    connected: boolean;
    version: string | null;
    edition: string | null;
    apoc_version: string | null;
    gds_version: string | null;
  };
  schema_ok: boolean | null;
  as_of_date: string;
}

export interface AppConfig {
  analytics: { lookback_months: number; stalled_days: number };
  expertise: { min_deals_per_domain: number };
  similarity: { similarity_tolerance: number; similarity_min_domains: number };
  assignment: {
    weight_fit: number;
    weight_availability: number;
    peer_discount: number;
    capacity_default: number;
    max_candidates: number;
  };
  forecast: { forecast_commit_threshold: number; forecast_best_case_threshold: number };
  domains: {
    embedding_model: string;
    related_top_k: number;
    related_min_similarity: number;
    related_discount: number;
  };
  scheduler: { recompute_cron: string };
  seed: { seed_random_seed: number };
}

export interface SeedResult {
  counts: Record<string, number>;
  expertise_edges: number;
  similar_pairs: number;
  duration_ms: number;
  as_of_date: string;
  seed: number;
}

export interface RecomputeResult {
  expertise_edges: number;
  similar_pairs: number;
  related_pairs: number;
  duration_ms: number;
  computed_at: string;
}

export interface RelatedDomain {
  domain: Domain;
  similarity: number;
  used_for_fit: boolean;
}

export interface DomainInfo {
  name: Domain;
  description: string | null;
  builtin: boolean;
  created_at: string | null;
  related: RelatedDomain[];
}

export interface DomainCreate {
  name: string;
  description: string;
}

// ---- sales people ----
export interface SalesPerson {
  id: string;
  name: string;
  email: string;
  region: Region;
  joined_on: string;
  active: boolean;
  capacity: number;
}

export interface ExpertiseRow {
  domain: Domain;
  handled: number;
  won: number;
  lost: number;
  win_rate: number | null;
  qualifies: boolean;
  last_won_at: string | null;
}

export interface SimilarPeer {
  id: string;
  name: string;
  matched_domains: Domain[];
  match_count: number;
  mean_abs_diff: number;
  score: number;
}

export interface SalesPersonDetail extends SalesPerson {
  open_count: number;
  availability: number;
  expertise: ExpertiseRow[];
  similar_peers: SimilarPeer[];
}

export interface SalesPersonUpdate {
  capacity?: number;
  active?: boolean;
}

// ---- clients / deals / activities ----
export interface Client {
  id: string;
  name: string;
  industry: string;
  size: ClientSize;
  region: Region;
  created_on: string;
}

export interface Deal {
  id: string;
  title: string;
  value: number;
  status: DealStatus;
  stage: Stage;
  domain: Domain;
  client_id: string;
  client_name: string;
  owner_id: string | null;
  owner_name: string | null;
  created_at: string;
  qualified_at: string | null;
  proposal_at: string | null;
  negotiation_at: string | null;
  expected_close_date: string;
  closed_at: string | null;
}

export interface ClientDetail extends Client {
  deals: Deal[];
}

export interface Activity {
  id: string;
  type: ActivityType;
  date: string;
  outcome: Outcome;
  deal_id: string;
  sales_person_id: string;
  sales_person_name: string;
}

export interface Recommendation {
  sales_person_id: string;
  name: string;
  rank: number;
  score: number;
  fit: number;
  availability: number;
  fit_type: FitType;
  reason: string;
  status: RecommendationStatus;
}

export interface UnavailableRep {
  id: string;
  name: string;
  reason: "INACTIVE" | "AT_CAPACITY";
  open_count: number;
  capacity: number;
}

export interface AssignmentResult {
  deal_id: string;
  domain: Domain;
  assignment_status: AssignmentStatus;
  assigned_to: { id: string; name: string } | null;
  candidates: Recommendation[];
  unavailable: UnavailableRep[];
  message: string;
}

export interface DealDetail extends Deal {
  activities: Activity[];
  recommendations: Recommendation[];
}

export interface DealFields {
  title: string;
  value: number;
  domain: Domain;
  expected_close_date: string;
  owner_id?: string | null;
}

export interface ClientWithDealCreate {
  client: { name: string; industry: string; size: ClientSize; region: Region };
  deal: DealFields;
}

export interface ClientCreateResult {
  client: Client;
  deal: Deal;
  assignment: AssignmentResult;
}

export interface ActivityCreate {
  deal_id: string;
  sales_person_id: string;
  type: ActivityType;
  date?: string;
  outcome: Outcome;
}

export interface DealFilters {
  status?: DealStatus;
  stage?: Stage;
  domain?: Domain;
  owner_id?: string;
  client_id?: string;
  closing_month?: string;
  limit?: number;
  offset?: number;
}

// ---- analytics ----
export interface Kpis {
  open_deals: number;
  open_value: number;
  won_this_month: number;
  clients_converted_this_month: number;
  win_rate_window: number | null;
  avg_cycle_days: number | null;
  avg_won_value: number | null;
  stalled_count: number;
}

export type StageCounts = Record<Stage, number>;

export interface PipelineRep {
  sales_person_id: string;
  name: string;
  open_count: number;
  capacity: number;
  open_value: number;
  by_stage: StageCounts;
}

export interface Pipeline {
  reps: PipelineRep[];
  unassigned_open_count: number;
}

export interface HeatmapCell {
  sales_person_id: string;
  domain: Domain;
  handled: number;
  won: number;
  win_rate: number | null;
  qualifies: boolean;
}

export interface Heatmap {
  reps: { id: string; name: string }[];
  domains: Domain[];
  cells: HeatmapCell[];
}

export interface StalledDeal {
  deal_id: string;
  title: string;
  owner_id: string | null;
  owner_name: string | null;
  client_name: string;
  domain: Domain;
  stage: Stage;
  last_activity_date: string | null;
  days_since_activity: number;
}

export interface LeaderboardRow {
  sales_person_id: string;
  name: string;
  clients_converted: number;
  won_value: number;
}

export interface Leaderboard {
  month: LeaderboardRow[];
  quarter: LeaderboardRow[];
}

export interface DomainTrend {
  months: string[];
  series: { domain: Domain; counts: number[] }[];
}

export interface ForecastTotals {
  expected_conversions: number;
  commit: number;
  best_case: number;
  expected_revenue: number;
  converted_so_far: number;
}

export interface ForecastDeal {
  deal_id: string;
  stage: Stage;
  value: number;
  p_deal: number;
  probability_source: ProbabilitySource;
}

export interface ForecastClient {
  client_id: string;
  client_name: string;
  probability: number;
  deals: ForecastDeal[];
}

export interface ForecastRep extends ForecastTotals {
  sales_person_id: string;
  name: string;
  clients: ForecastClient[];
}

export interface Forecast {
  month: string;
  team: ForecastTotals;
  by_rep: ForecastRep[];
}

export interface Backtest {
  month: string;
  asof: string;
  by_rep: {
    sales_person_id: string;
    name: string;
    predicted_expected: number;
    actual: number;
    abs_error: number;
  }[];
  team: { predicted_expected: number; actual: number; abs_error: number };
  mean_abs_error: number;
  limitations: string[];
}

export interface SimilarityCompareRow {
  rep_a: string;
  rep_b: string;
  rule_score: number | null;
  rule_matched_domains: Domain[] | null;
  gds_score: number | null;
}

// ---- graph explorer ----
export type GraphNodeType = "SalesPerson" | "Deal" | "Client" | "Domain";
export type GraphLinkType = "OWNS" | "FOR_CLIENT" | "IN_DOMAIN" | "EXPERTISE_IN" | "SIMILAR_TO";

export interface GraphNode {
  id: string;
  label: string;
  type: GraphNodeType;
  props: Record<string, unknown>;
}

export interface GraphLink {
  source: string;
  target: string;
  type: GraphLinkType;
  props: Record<string, unknown>;
}

export interface Subgraph {
  nodes: GraphNode[];
  links: GraphLink[];
}
