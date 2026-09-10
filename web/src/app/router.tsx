/** Route tree: submissions, projects, and the form builder. */

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
import { MonitoringPage } from "@/pages/MonitoringPage";
import { SamplePage } from "@/pages/SamplePage";
import { FormsPage } from "@/pages/FormsPage";
import { BuilderPage } from "@/pages/BuilderPage";
import { LoginPage } from "@/pages/LoginPage";
import { PeoplePage } from "@/pages/PeoplePage";
import { RolesPage } from "@/pages/RolesPage";

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
    // TanStack Router signals a redirect by throwing the object `redirect()`
    // returns — the router catches it and navigates. It is control flow, not
    // an error, so the rule is right in general and wrong exactly here.
    // eslint-disable-next-line @typescript-eslint/only-throw-error
    throw redirect({ to: "/submissions", search: {} });
  },
});

const loginRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/login",
  component: LoginPage,
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

const sampleRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/projects/$projectId/sample",
  component: SamplePage,
});

const monitoringRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/projects/$projectId/monitoring",
  component: MonitoringPage,
});

const formsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/forms",
  component: FormsPage,
});

const peopleRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/people",
  component: PeoplePage,
});

const rolesRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/roles",
  component: RolesPage,
});

/** `$formId` is the form row's id, not the §1 `formId` key — the draft and
 *  the versions hang off the row. */
const builderRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/forms/$formId",
  component: BuilderPage,
});

/** Exported for tests, which mount one route over a memory history rather than
 *  the browser history this module's `router` is bound to. */
export const routeTree = rootRoute.addChildren([
  indexRoute,
  loginRoute,
  submissionsRoute,
  submissionRoute,
  projectsRoute,
  projectKeysRoute,
  sampleRoute,
  monitoringRoute,
  formsRoute,
  builderRoute,
  peopleRoute,
  rolesRoute,
]);

export const router = createRouter({ routeTree });

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}
