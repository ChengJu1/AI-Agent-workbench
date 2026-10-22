import { jsonBody, requestJson } from "../../api/http";

export type Stage = "saved" | "preparing" | "applied" | "test" | "interview" | "offer" | "rejected" | "withdrawn";
export type KitFlag = "" | "draft" | "chat" | "converted" | "file" | "missing";
export type KitItem = {
  label: string; section: string; type: string; required: boolean; options: string[]; value: string; flag: KitFlag; note: string;
  source: { kind: string; ref: string; version?: number | null }; transform: string; edited?: boolean;
};
export type Kit = { profile_id: string; profile_version: number; form_url: string; items: KitItem[] };
export type ApplicationEvent = { id: number; actor: string; body: Record<string, unknown>; created_at: string };
export type Application = {
  id: string; company: string; position: string; url: string; stage: Stage; stage_label: string; deadline: string;
  next_event_at: string; next_event: string; note: string; applied_at: string; revision: number; created_at: string; updated_at: string;
  kit: Kit | null; has_kit?: boolean; events?: ApplicationEvent[];
  jd: string; has_jd?: boolean; tailoring: Tailoring | null; interview_prep: InterviewPrep | null; has_prep?: boolean;
};
export type Tailoring = { score: number; matched: string[]; missing: string[]; suggestions: string[]; profile_id: string; profile_version: number;
  profile_name: string; base_profile_id: string; base_profile_version: number; created_at: string };
export type InterviewQuestion = { category: "技术" | "项目" | "行为" | "岗位理解" | "反问"; question: string; points: string[]; based_on: string };
export type InterviewPrep = { questions: InterviewQuestion[]; note: string; created_at: string };
export type ApplicationFields = Pick<Application, "company" | "position" | "url" | "deadline" | "next_event_at" | "next_event" | "note" | "jd">;

export type BriefItem = { ref: string; text: string; detail: string };
export type Brief = { date: string; total: number; sections: { id: string; title: string; items: BriefItem[] }[] };
export const fetchBrief = (signal?: AbortSignal) => requestJson<Brief>("/api/brief", { signal });
export const fetchApplications = (signal?: AbortSignal) => requestJson<Application[]>("/api/applications", { signal });
export const fetchApplication = (id: string, signal?: AbortSignal) => requestJson<Application>(`/api/applications/${id}`, { signal });
export const createApplication = (body: ApplicationFields, signal?: AbortSignal) => requestJson<Application>("/api/applications", { ...jsonBody(body), signal });
export const updateApplication = (item: Application, body: ApplicationFields, signal?: AbortSignal) =>
  requestJson<Application>(`/api/applications/${item.id}`, { ...jsonBody({ ...body, expected_revision: item.revision }), method: "PUT", signal });
export const changeStage = (item: Application, stage: Stage, signal?: AbortSignal) =>
  requestJson<Application>(`/api/applications/${item.id}/stage`, { ...jsonBody({ expected_revision: item.revision, stage }), signal });
export const editKitItem = (item: Application, index: number, value: string, signal?: AbortSignal) =>
  requestJson<Application>(`/api/applications/${item.id}/kit`, { ...jsonBody({ expected_revision: item.revision, index, value }), signal });
export const deleteApplication = (id: string, signal?: AbortSignal) => requestJson<{ deleted: boolean }>(`/api/applications/${id}`, { method: "DELETE", signal });

// ---------- profiles ----------
export type DateValue = { precision: "year" | "month" | "day"; year: number; month?: number | null; day?: number | null };
export type Education = { school: string; degree: string; major: string; gpa?: string; period: { start: DateValue; end?: DateValue | null; present: boolean } };
export type Period = { organization: string; title: string; description: string; period: { start: DateValue; end?: DateValue | null; present: boolean } };
export type ProfileData = { basics: Record<string, string>; education: Education[]; experience: Period[]; projects: Period[]; skills: string[]; answers: Record<string, string> };
export type ProfileSummary = { id: string; name: string; latest_version: number; reviewed_version: number | null; updated_at: string };
export type Profile = ProfileSummary & { version: number; review_state: "reviewed" | "draft"; data: ProfileData; versions: { version: number; review_state: string; created_at: string }[] };

export const fetchProfiles = (signal?: AbortSignal) => requestJson<ProfileSummary[]>("/api/profiles", { signal });
export const fetchProfile = (id: string, signal?: AbortSignal) => requestJson<Profile>(`/api/profiles/${id}`, { signal });
export const saveProfile = (name: string, data: ProfileData, previous: Profile | null, signal?: AbortSignal) =>
  requestJson<Profile>(previous ? `/api/profiles/${previous.id}/versions` : "/api/profiles",
    { ...jsonBody({ name, data, ...(previous ? { expected_version: previous.latest_version } : {}) }), signal });
export const deleteProfile = (id: string, signal?: AbortSignal) => requestJson<{ deleted: boolean }>(`/api/profiles/${id}`, { method: "DELETE", signal });
