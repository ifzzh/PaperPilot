import base from './playwright.config';
import {defineConfig} from '@playwright/test';
export default defineConfig({...base,testDir:'./compat-tests',use:{...base.use,launchOptions:{executablePath:'/opt/microsoft/msedge/msedge'}}});
