/**
 * ESLint config for the React + Vite frontend.
 *
 * Goals:
 *  - Catch broken imports / undefined variables / unused vars (the
 *    classes of bug that the cleanup work exposed multiple times).
 *  - Enforce React + Hooks correctness (rules-of-hooks +
 *    exhaustive-deps) — these are the single biggest source of subtle
 *    runtime bugs in the codebase.
 *  - Stay out of the way on style — Prettier owns that.
 *
 * Run from the frontend dir:
 *   npm run lint         # report problems
 *   npm run lint:fix     # auto-fix what's auto-fixable
 */
module.exports = {
    root: true,
    env: {
        browser: true,
        es2022: true,
        node: true,
    },
    parserOptions: {
        ecmaVersion: 2022,
        sourceType: "module",
        ecmaFeatures: { jsx: true },
    },
    settings: {
        react: { version: "18" },
    },
    extends: [
        "eslint:recommended",
        "plugin:react/recommended",
        "plugin:react/jsx-runtime",
        "plugin:react-hooks/recommended",
        "prettier",
    ],
    plugins: ["react", "react-hooks", "react-refresh"],
    rules: {
        // React: jsx-runtime makes React-in-scope redundant.
        "react/react-in-jsx-scope": "off",
        // Permit `let { foo } = …` followed by reassignment.
        "react/no-unescaped-entities": "off",
        // Prop-types are heavy and the codebase doesn't use them.
        "react/prop-types": "off",
        // Hooks: the two non-negotiable rules.
        "react-hooks/rules-of-hooks": "error",
        "react-hooks/exhaustive-deps": "warn",
        // No unused vars — but `_` prefix opts out so we can still
        // destructure required positional args.
        "no-unused-vars": [
            "warn",
            {
                argsIgnorePattern: "^_",
                varsIgnorePattern: "^_",
                ignoreRestSiblings: true,
            },
        ],
        // console.error/warn are intentional in this codebase (see
        // `utils/log.js` for the rationale). Only log/info/debug are
        // banned at run time, but ESLint doesn't need to police that.
        "no-console": "off",
        // Vite-specific: keep fast-refresh boundaries clean.
        "react-refresh/only-export-components": [
            "warn",
            { allowConstantExport: true },
        ],
    },
    overrides: [
        {
            files: ["**/*.test.{js,jsx}", "**/*.spec.{js,jsx}"],
            env: { jest: true, node: true },
        },
    ],
    ignorePatterns: [
        "dist/",
        "build/",
        "node_modules/",
        "vite.config.js",
        "postcss.config.js",
        "tailwind.config.js",
    ],
};
