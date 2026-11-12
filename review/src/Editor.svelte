<script module>
  // The IDS Workshop's editor, with the data ids-input ships.
  import { babelStoneAdapter } from 'ids-input/adapter'
  import ids from 'ids-input/data/babelstone-ids.tsv.gz?url'
  import projectIds from 'ids-input/data/ids-project.tsv.gz?url'
  import overwriteIds from 'ids-input/data/ids-overwrites.tsv?url'
  import components from 'ids-input/data/ids-components.tsv?url'
  import parts from 'ids-input/data/ids-parts.json?url'
  import forms from 'ids-input/data/component-forms.tsv?url'
  import names from 'ids-input/data/component-names.tsv?url'
  import folds from 'ids-input/data/component-name-folds.tsv?url'
  import characterInfo from 'ids-input/data/character-info.json.gz?url'
  import characters from 'ids-input/data/character-vocabulary.tsv.gz?url'
  const adapter = babelStoneAdapter({ ids, additionalIds: projectIds, overwrite: overwriteIds, components, parts, forms, names, folds, characters, characterInfo })
</script>
<script>
  import { IdsInput } from 'ids-input/svelte'
  let { value = $bindable(''), onuse } = $props()
</script>

<IdsInput {adapter} bind:value locale="en" {onuse} recentKey="idsDesk.recentParts" />
