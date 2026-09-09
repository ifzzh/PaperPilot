'use strict';

(function () {
    const call = (name, ...args) => {
        const handler = window[name];
        if (typeof handler === 'function') handler(...args);
    };

    const index = (element) => {
        const value = Number.parseInt(element.dataset.index || '', 10);
        return Number.isSafeInteger(value) && value >= 0 ? value : null;
    };

    const actions = {
        'show-daily-settings': () => call('showDailyArxivSettingsModal'),
        'toggle-filter-section': (_event, element) => call('toggleFilterSection', element),
        'add-daily-category': () => call('addDailyArxivCategory'),
        'add-daily-category-quick': (_event, element) => call('addDailyArxivCategoryQuick', element.dataset.category),
        'show-add-institution': () => call('showAddInstitutionModal'),
        'choose-rdf-file': () => document.getElementById('rdf-file-input')?.click(),
        'cancel-import': () => call('cancelImport'),
        'reset-import': () => call('resetImport'),
        'switch-import-overview': () => call('switchToOverview'),
        'choose-export-file': () => document.getElementById('export-file-input')?.click(),
        'close-institution-modal': () => call('closeInstitutionModal'),
        'add-institution-variant': () => call('addVariantInModal'),
        'delete-institution': () => call('deleteInstitutionInModal'),
        'save-institution': () => call('saveInstitutionInModal'),
        'close-onboarding': () => call('closeOnboardingModal'),
        'export-markdown': () => call('exportMarkdown'),
        'export-pdf': () => call('exportPDF'),
        'reload-page': () => window.location.reload(),
        'translation-logs': (event, element) => call('showTranslationLogs', element.dataset.paperId, event),
        'cancel-translation-status': (event, element) => call('cancelTranslationFromStatus', element.dataset.paperId, event),
        'cancel-translation-queue': (event, element) => call('cancelTranslationFromQueue', element.dataset.paperId, event),
        'open-chinese': (event, element) => call('openChineseVersion', element.dataset.paperId, event),
        'request-translation': (event, element) => call('requestTranslation', element.dataset.paperId, event),
        'analysis-logs': (event, element) => call('showAnalysisLogs', element.dataset.paperId, event),
        'cancel-analysis': (event, element) => call('cancelAnalysis', element.dataset.paperId, event),
        'cancel-analysis-status': (event, element) => call('cancelAnalysisFromStatus', element.dataset.paperId, event),
        'cancel-analysis-queue': (event, element) => call('cancelAnalysisFromQueue', element.dataset.paperId, event),
        'view-analysis': (event, element) => call('viewAnalysisResult', element.dataset.paperId, event),
        'request-analysis': (event, element) => call('requestAnalysis', element.dataset.paperId, event),
        'open-chat': (event, element) => call('openChat', element.dataset.paperId, event),
        'remove-reading-list': (event, element) => call('removeFromReadingList', element.dataset.paperId, event),
        'add-reading-list': (event, element) => call('addToReadingList', element.dataset.paperId, event),
        'expand-text': (_event, element) => call('toggleTextExpand', element),
        'collapse-text': (_event, element) => call('toggleTextCollapse', element),
        'stop-propagation': (event) => event.stopPropagation(),
        'copy-bibtex': (event, element) => {
            event.stopPropagation();
            call('copyBibtex', element.dataset.paperId);
        },
        'toggle-info-section': (_event, element) => call('toggleInfoSection', element),
        'open-recent-paper': (_event, element) => call('openPaperFromRecent', element.dataset.paperId),
        'refresh-translation-log': (_event, element) => call('refreshLogs', element.dataset.taskId, element.dataset.paperId),
        'cancel-translation': (_event, element) => call('cancelTranslation', element.dataset.taskId, element.dataset.paperId),
        'restart-daily-fetch': () => call('restartDailyArxivFetch'),
        'remove-daily-institution': (event, element) => {
            event.stopPropagation();
            call('removeDailyArxivInstitution', element.dataset.tier, index(element));
        },
        'add-daily-institution': (_event, element) => call('addDailyArxivInstitution', element.dataset.tier),
        'remove-notification': (_event, element) => call('removeNotificationWithAnimation', element.dataset.notificationId),
        'open-agent-settings': () => {
            call('switchTab', 'setting');
            window.setTimeout(() => document.querySelector('[data-setting="agentic"]')?.click(), 100);
        },
        'fetch-daily': () => call('triggerFetchPapers', false),
        'fetch-daily-all': () => call('triggerFetchAllCategories', false),
        'show-daily-detail': (_event, element) => call('showDailyArxivDetail', index(element)),
        'retry-daily-asset': (event, element) => call('retryDailyArxivAsset', index(element), event),
        'daily-remove-reading-list': (event, element) => call('onDailyArxivRemoveFromReadingList', index(element), event),
        'daily-add-reading-list': (event, element) => call('onDailyArxivAddToReadingList', index(element), event),
        'toggle-first-affiliation': () => call('toggleFirstAffiliationFilter'),
        'hide-unknown-institutions': () => call('hideAllUnknownInstitutions'),
        'extract-affiliations': (_event, element) => call('extractAffiliationsForPaper', index(element)),
        'generate-summary': (_event, element) => call('generateBriefSummaryForPaper', index(element)),
        'close-daily-detail': () => call('closeDailyArxivDetail'),
        'close-daily-detail-overlay': (event, element) => {
            if (event.target === element) call('closeDailyArxivDetail');
        },
        'daily-add-and-close': (event, element) => {
            call('onDailyArxivAddToReadingList', index(element), event);
            call('closeDailyArxivDetail');
        }
    };

    document.addEventListener('click', (event) => {
        const element = event.target.closest?.('[data-action]');
        if (!element) return;
        const handler = actions[element.dataset.action];
        if (handler) handler(event, element);
    });

    document.addEventListener('dragstart', (event) => {
        const element = event.target.closest?.('[data-daily-tier-item]');
        if (!element) return;
        call('onDailyArxivInstitutionDragStart', event, element.dataset.tier, index(element));
    });

    document.addEventListener('dragend', (event) => {
        if (event.target.closest?.('[data-daily-tier-item]')) {
            call('onDailyArxivInstitutionDragEnd', event);
        }
    });

    document.addEventListener('dragover', (event) => {
        if (event.target.closest?.('[data-daily-tier-dropzone]')) {
            call('onDailyArxivInstitutionDragOver', event);
        }
    });

    document.addEventListener('dragleave', (event) => {
        if (event.target.closest?.('[data-daily-tier-dropzone]')) {
            call('onDailyArxivInstitutionDragLeave', event);
        }
    });

    document.addEventListener('drop', (event) => {
        const element = event.target.closest?.('[data-daily-tier-dropzone]');
        if (!element) return;
        call('onDailyArxivInstitutionDrop', event, element.dataset.tier);
    });

    document.addEventListener('error', (event) => {
        const image = event.target.closest?.('img[data-image-fallback]');
        if (!image) return;
        image.style.display = 'none';
        const fallback = image.nextElementSibling;
        if (fallback && image.dataset.imageFallback !== 'hide') {
            fallback.style.display = image.dataset.imageFallback;
        }
    }, true);
})();
