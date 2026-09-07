/** A small form with a repeat and a sensitive field, for the editor tests. */

import type { FormIr, QuestionNode } from "@/builder/ir";

const q = (
  id: string,
  dataType: string,
  extra: Partial<QuestionNode> = {},
): QuestionNode => ({
  type: "question",
  id,
  dataType,
  label: { en: id.replace(/_/g, " ") },
  ...extra,
});

export function fixture(): FormIr {
  return {
    irVersion: "0.1",
    formId: "fx",
    version: 1,
    title: { en: "Fixture" },
    defaultLanguage: "en",
    languages: ["en"],
    children: [
      q("age", "integer"),
      q("consent", "select_one"),
      {
        type: "group",
        id: "hh",
        label: { en: "Household" },
        children: [
          q("size", "integer"),
          {
            type: "repeat",
            id: "members",
            label: { en: "Members" },
            minInstances: 0,
            children: [
              q("name", "text"),
              q("income", "decimal", { sensitive: true }),
            ],
          },
        ],
      },
    ],
  };
}
