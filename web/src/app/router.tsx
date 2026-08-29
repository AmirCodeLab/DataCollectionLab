/** Route tree. Two views: the submission list, and one submission. */

import {
  createRootRoute,
  createRoute,
  createRouter,
  redirect,
} from "@tanstack/react-router";

import { SUBMISSION_STATUSES, type SubmissionStatus } from "@/api/types";
import { Layout } from "./Layout";
import { SubmissionsPage } from "@/pages/SubmissionsPage";
import { SubmissionPage } from "@/pages/SubmissionPage";
import { ProjectsPage } from "@/pages/ProjectsPage";
import { ProjectKeysPage } from "@/pages/ProjectKeysPage";

export const PAGE_SIZE = 50;

export interface SubmissionsSearch {
  formId?: string;
  status?: SubmissionStatus;
  /** Absent means the first page — the default stays out of the URL. */
  offset?: number;
}

const rootRoute = createRootRoute({ component: Layout });

const indexRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/",
  beforeLoad: () => {
    throw redirect({ to: "/submissions", search: {} });
  },
});

const submissionsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/submissions",
  component: SubmissionsPage,
  // Filters live in the URL so a view is a link someone can send on. Anything
  // unrecognised is dropped rather than passed through to the API.
  validateSearch: (search: Record<string, unknown>): SubmissionsSearch => {
    const status =
      typeof search.status === "string" &&
      (SUBMISSION_STATUSES as readonly string[]).includes(search.status)
        ? (search.status as SubmissionStatus)
        : undefined;
    const formId =
      typeof search.formId === "string" && search.formId !== ""
        ? search.formId
        : undefined;
    const offset = Number(search.offset);
    return {
      formId,
      status,
      offset:
        Number.isFinite(offset) && offset > 0 ? Math.floor(offset) : undefined,
    };
  },
});

const submissionRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/submissions/$submissionId",
  component: SubmissionPage,
});

const projectsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/projects",
  component: ProjectsPage,
});

const projectKeysRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/projects/$projectId/keys",
  component: ProjectKeysPage,
});

const routeTree = rootRoute.addChildren([
  indexRoute,
  submissionsRoute,
  submissionRoute,
  projectsRoute,
  projectKeysRoute,
]);

export const router = createRouter({ routeTree });

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}
