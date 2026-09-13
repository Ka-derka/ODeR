# Creator usability priorities

Creator usability roadmap, September 2026. The first focused-workspace pass is implemented; remaining proposals are listed below.

## Implemented in the first workspace pass

- Home: create from a folder, open a project, start blank, reopen recent projects, or resume the current project without losing edits.
- Original native splash screen with real startup phases and no artificial delay.
- Project tree, focused center editor, live preview and check/create actions on the right. A compact Home/document/save header makes the active project and unsaved state clear.
- Name, cover, summary and description first. Optional details, publishing and torrent settings are collapsible and retain all existing values.
- Add File puts sources first and hides platform/checksum fields under more details. Online-only files no longer require deselecting torrent sharing first. New files start with editable copies of the library's author, category and license.
- Explicit **Prepare next revision** in the Library menu increments the update number, retains the library ID, and opens version/release-note fields. Rebuilding does not silently increment revisions.
- Background package creation with honest indeterminate progress. Completion offers the output folder, testing via the installed ODeR file association, and copyable instructions that distinguish payload seeding from T2 package seeding.
- Optional author/category suggestions remain visible but do not interrupt every build. Other warnings and blocking errors remain checked.
- Safer Save As and file-editor roundtrips preserve relative source files, artwork and torrent references.

## Remaining priorities

## First: keep large builds responsive

Hashing and package/torrent creation now run in a worker thread. Folder scanning and pre-build validation still need background execution. Add stage/file/byte progress and elapsed time. Safe cancellation needs builder support to clean up temporary outputs and keep the last successful release intact; the current build dialog deliberately cannot be dismissed mid-write.

## Make the file tree behave like a familiar file manager

Use a single nested folder tree rather than separate conceptual groups. Support dropping files/folders into a selected folder, moving them by drag-and-drop, renaming in place, multi-select and a search box. Keep advanced source variants in a details panel; the main flow should be "add these files to this folder".

## Describe inclusion choices by their effects

The import dialog currently exposes Catalog, Bundle and Torrent checkboxes. Prefer **Include in library**, **Put file inside the package**, and **Share through torrent**, with tooltips and a live estimate of package size. Disabling inclusion should disable the other options. Provide presets such as **Small package, torrent delivery**, **Everything offline**, and **Links only**, with an editable per-file override.

## Give publishing a guided release flow

Expand the implemented completion guidance into **Prepare → Review changes → Build → Publish/seed**. Add **Open update torrent** alongside the existing output-folder and sharing-instruction actions. The payload torrent and T2 package-update torrent represent different data, and must keep distinct seed-folder instructions.

An **Update existing project from folder** action should compare paths/content and preserve artifact IDs, show added/changed/missing files, and ask before removing entries. The implemented **Prepare next revision** preserves the library UUID, but folder synchronization still needs a review/merge flow.

## Make validation actionable

Each error should jump to the affected file or field. Group repeated problems and show blocking errors ahead of metadata suggestions. Warn inline for invalid URLs. Optional descriptive fields no longer interrupt each build, but issue navigation and grouping remain future work.

## Reduce form density and protect editing work

The simpler forms and Version/Revision explanations are in place. Next add project-wide undo/redo, autosaved drafts and recovery after interruption. A saved project and a published release should have visibly different states.

Suggested next order: safe progress/cancel; folder synchronization that preserves IDs; richer file-tree editing; validation navigation; draft recovery.
