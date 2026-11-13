import '../../demo/static/design/tokens.css'
import '../../demo/static/design/base.css'
import '../../demo/static/design/controls.css'
import 'ids-input/fonts.css'
import './app.css'
import { mount } from 'svelte'
import App from './App.svelte'

mount(App, { target: document.getElementById('app') })
