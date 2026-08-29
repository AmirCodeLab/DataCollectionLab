/** ESLint flat config for the console.
 *
 * There was no config here for weeks and `npm run lint` was wired to a binary
 * that was not installed, so the script failed open in every place nobody read
 * the exit code. A gate that cannot fail is worse than no gate: it produces the
 * paperwork of having been checked.
 *
 * Type-aware rules are on. Most of what this console does wrong would be a type
 * error rather than a style one — a floating promise in the decryption path, an
 * `any` that silently swallows a wire-shape change — and those need the type
 * checker, not just the parser.
 */

import js from "@eslint/js";
import globals from "globals";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";
import tseslint from "typescript-eslint";

export default tseslint.config(
  {
    // Build output and dependencies are not ours to lint.
    ignores: ["dist/**", "node_modules/**", "coverage/**"],
  },

  // Config files themselves run in Node and are not part of the app's tsconfig.
  {
    files: ["*.config.js", "*.config.ts", "postcss.config.js", "tailwind.config.js"],
    languageOptions: {
      globals: globals.node,
    },
  },

  {
    files: ["src/**/*.{ts,tsx}"],
    extends: [
      js.configs.recommended,
      ...tseslint.configs.recommendedTypeChecked,
      // `.flat` is the flat-config variant; the top-level `recommended-latest`
      // is still eslintrc-shaped and errors out under flat config.
      reactHooks.configs.flat["recommended-latest"],
    ],
    languageOptions: {
      ecmaVersion: 2022,
      globals: globals.browser,
      parserOptions: {
        project: ["./tsconfig.json"],
        tsconfigRootDir: import.meta.dirname,
      },
    },
    plugins: {
      "react-refresh": reactRefresh,
    },
    rules: {
      "react-refresh/only-export-components": [
        "warn",
        { allowConstantExport: true },
      ],

      // The console's own rules, in priority order.

      // A dropped promise in the decryption path means a key file that silently
      // never loads, or an error that never reaches the panel. Both look
      // identical to "this submission has no answers".
      "@typescript-eslint/no-floating-promises": "error",

      // `catch (cause: unknown)` and `String(cause)` are the house style; an
      // implicit `any` from a wire response is how a renamed field becomes
      // `undefined` on screen instead of a build failure.
      "@typescript-eslint/no-explicit-any": "error",

      // Deliberate unused args are prefixed with _; anything else is a leftover.
      "@typescript-eslint/no-unused-vars": [
        "error",
        { argsIgnorePattern: "^_", varsIgnorePattern: "^_" },
      ],
    },
  },

  // Tests may reach for Node globals and are not part of the app's tsconfig
  // include, so type-aware rules would have nothing to work from.
  {
    files: ["src/**/*.test.{ts,tsx}", "src/test/**/*.{ts,tsx}"],
    extends: [tseslint.configs.disableTypeChecked],
    languageOptions: {
      globals: { ...globals.browser, ...globals.node },
    },
    rules: {
      "@typescript-eslint/no-unsafe-assignment": "off",
      "@typescript-eslint/no-unsafe-member-access": "off",
    },
  },
);
