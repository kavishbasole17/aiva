import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: ["dist/", "eslint.config.js"] },
  ...tseslint.configs.recommendedTypeChecked,
  {
    languageOptions: {
      parserOptions: {
        projectService: true,
        tsconfigRootDir: import.meta.dirname,
      },
    },
    rules: {
      "@typescript-eslint/no-explicit-any": "error",
      "@typescript-eslint/no-non-null-assertion": "error",
      "no-restricted-syntax": [
        "error",
        {
          selector: "Literal[value=/^https?:\\/\\//]",
          message: "Absolute URLs are banned in source under the air-gap policy.",
        },
        {
          selector: "TemplateElement[value.raw=/^https?:\\/\\//]",
          message: "Absolute URLs are banned in source under the air-gap policy.",
        },
      ],
    },
  },
);
