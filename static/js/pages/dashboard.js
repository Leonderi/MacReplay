(function() {
    let streamsRefreshInterval;

    function initDashboardPage(pageData) {
        pageData = pageData || {};

// Toast Notification Functions
function showNotification(message, type = 'success', duration = 3000) {
    const toastType = type === 'danger' ? 'error' : type;
    if (typeof showToast === 'function') {
        showToast(message, toastType, duration);
    }
}

function refreshStreams() {
    const container = document.getElementById('streamsContainer');
    if (!container) return;
    return fetch('/streaming')
        .then(response => response.json())
        .then(data => {
            displayStreams(data);
            return data;
        })
        .catch(error => {
            console.error('Error fetching streams:', error);
            if (container) {
                container.innerHTML =
                    '<div class="alert alert-danger"><i class="fas fa-exclamation-triangle"></i> Error loading stream data</div>';
            }
            return {};
        });
}

function refreshDashboardStats() {
    return fetch('/api/dashboard/stats')
        .then(response => response.json())
        .then(stats => {
            setText('statActiveStreams', stats.active_streams ?? '-');
            setText('statActiveClients', `Clients: ${stats.active_clients ?? '-'}`);
            setText('statPortals', `${stats.portals_enabled ?? '-'} / ${stats.portals_total ?? '-'}`);
            setText(
                'statPortalTypes',
                `Stalker: ${stats.stalker_portals ?? '-'} · Xtream: ${stats.xtream_portals ?? '-'}`
            );
            setText('statChannels', `${stats.channels_enabled ?? '-'} / ${stats.channels_total ?? '-'}`);
            setText('statEvents', `Event: ${stats.event_channels_enabled ?? '-'}`);
            setText('statGroups', `${stats.groups_active ?? '-'} / ${stats.groups_total ?? '-'}`);
            setText('statLastEpg', `Last EPG: ${formatTimestamp(stats.last_epg_refresh)}`);
            setText(
                'statMacExpiry',
                `MACs: 7d ${stats.macs_expiring_7d ?? 0} · 30d ${stats.macs_expiring_30d ?? 0} · expired ${stats.macs_expired ?? 0}`
            );
            setText(
                'statXtreamExpiry',
                `Xtream Logins: 7d ${stats.xtream_logins_expiring_7d ?? 0} · 30d ${stats.xtream_logins_expiring_30d ?? 0}`
            );
            renderRecentChannels(stats.recent_channels || []);
            renderTopPortals(stats.top_portals_active || []);
            renderTopMacDurations(stats.top_mac_durations || []);
            renderTopFailedMacs(stats.top_failed_macs || []);
            renderTopReliableChannels(stats.top_reliable_channels || []);
            renderSpeedtest('proxy', stats.speedtest_proxy || null);
            renderSpeedtest('direct', stats.speedtest_direct || null);
            setStatusBadge('statusEpgBadge', 'EPG', stats.status_epg);
            setStatusBadge('statusStreamingBadge', 'Streaming', stats.status_streaming || 'ok');
        })
        .catch(error => {
            console.error('Error loading dashboard stats:', error);
        });
}

function displayStreams(streams) {
    const container = document.getElementById('streamsContainer');
    if (!container) return;

    if (!streams || Object.keys(streams).length === 0) {
        container.innerHTML = '<div class="alert alert-info"><i class="fas fa-info-circle"></i> No active streams</div>';
        return;
    }

    let html = '<div class="table-responsive"><table class="table table-striped dashboard-streams-table"><thead><tr><th>Portal</th><th>Channel</th><th>MAC</th><th>Client IP</th><th>Start Time</th><th>Duration</th></tr></thead><tbody>';

    Object.keys(streams).forEach(portalId => {
        streams[portalId].forEach(stream => {
            const startTime = new Date(stream['start time'] * 1000);
            const duration = Math.floor((Date.now() - startTime.getTime()) / 1000);
            const durationStr = formatDuration(duration);
            // Escape HTML to prevent XSS
            const portalName = escapeHtml(stream['portal name']);
            const channelName = escapeHtml(stream['channel name']);
            const sourcePortal = escapeHtml(stream['source portal name'] || '');
            const sourceChannel = escapeHtml(stream['source channel name'] || '');
            const sourceTags = Array.isArray(stream['source tags']) ? stream['source tags'] : [];
            const sourceTagHtml = sourceTags.length
                ? `<div class="small mt-1">${sourceTags.map(t => `<span class="badge bg-secondary me-1">${escapeHtml(String(t))}</span>`).join('')}</div>`
                : '';
            const sourceInfo = (sourcePortal || sourceChannel)
                ? `<div class="small text-info">Source: ${sourcePortal || '-'} · ${sourceChannel || '-'}</div>${sourceTagHtml}`
                : '';
            const mac = escapeHtml(stream.mac);
            const client = escapeHtml(stream.client);

            html += `
                <tr>
                    <td>${portalName}</td>
                    <td>${channelName}${sourceInfo}</td>
                    <td><code>${mac}</code></td>
                    <td>${client}</td>
                    <td>${startTime.toLocaleString()}</td>
                    <td>${durationStr}</td>
                </tr>
            `;
        });
    });

    html += '</tbody></table></div>';
    container.innerHTML = html;
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function formatDuration(seconds) {
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    const secs = seconds % 60;

    if (hours > 0) {
        return `${hours}h ${minutes}m ${secs}s`;
    } else if (minutes > 0) {
        return `${minutes}m ${secs}s`;
    } else {
        return `${secs}s`;
    }
}

function formatTimestamp(value) {
    if (!value) return '-';
    const parsed = new Date(value);
    if (!Number.isNaN(parsed.getTime())) return parsed.toLocaleString();
    const numeric = Number(value);
    if (!Number.isNaN(numeric) && numeric > 0) {
        const ms = numeric > 1e12 ? numeric : (numeric * 1000);
        const numDate = new Date(ms);
        if (!Number.isNaN(numDate.getTime())) return numDate.toLocaleString();
    }
    return String(value);
}

function setText(id, value) {
    const el = document.getElementById(id);
    if (el) el.textContent = value;
}

function setStatusBadge(id, label, state) {
    const el = document.getElementById(id);
    if (!el) return;
    const normalized = String(state || 'unknown').toLowerCase();
    el.classList.remove('bg-success', 'bg-warning', 'bg-danger', 'bg-secondary');
    if (normalized === 'ok') el.classList.add('bg-success');
    else if (normalized === 'stale') el.classList.add('bg-warning');
    else if (normalized === 'error') el.classList.add('bg-danger');
    else el.classList.add('bg-secondary');
    el.textContent = `${label}: ${normalized.toUpperCase()}`;
}

function renderRecentChannels(items) {
    const list = document.getElementById('recentChannelsList');
    if (!list) return;
    if (!items || items.length === 0) {
        list.classList.add('text-muted');
        list.textContent = 'No active streams.';
        return;
    }
    list.classList.remove('text-muted');
    list.innerHTML = items.map(item => {
        const channel = escapeHtml(item.channel_name || '-');
        const portal = escapeHtml(item.portal_name || '-');
        const sourcePortal = escapeHtml(item.source_portal_name || '');
        const sourceChannel = escapeHtml(item.source_channel_name || '');
        const sourceTags = Array.isArray(item.source_tags) ? item.source_tags : [];
        const sourceTagsHtml = sourceTags.length
            ? `<div class="dashboard-recent-meta">${sourceTags.map(t => `<span class="badge bg-secondary me-1">${escapeHtml(String(t))}</span>`).join('')}</div>`
            : '';
        const sourceLine = (sourcePortal || sourceChannel)
            ? `<div class="dashboard-recent-meta">Source: ${sourcePortal || '-'} · ${sourceChannel || '-'}</div>${sourceTagsHtml}`
            : '';
        const client = escapeHtml(item.client || '-');
        const started = formatTimestamp((item.start_time || 0) * 1000);
        return `
            <div class="dashboard-recent-item">
                <div class="dashboard-recent-main">
                    <div class="dashboard-recent-channel">${channel}</div>
                    <div class="dashboard-recent-meta">${portal} · ${client}</div>
                    ${sourceLine}
                </div>
                <div class="dashboard-recent-time">${started}</div>
            </div>
        `;
    }).join('');
}

function renderTopPortals(items) {
    const list = document.getElementById('topPortalsList');
    if (!list) return;
    if (!items || items.length === 0) {
        list.classList.add('text-muted');
        list.textContent = 'No active streams.';
        return;
    }
    list.classList.remove('text-muted');
    list.innerHTML = items.map(item => `
        <div class="dashboard-simple-item">
            <strong>${escapeHtml(item.portal_name || '-')}</strong>
            <span>${item.count || 0}</span>
        </div>
    `).join('');
}

function renderTopMacDurations(items) {
    const list = document.getElementById('topMacDurationsList');
    if (!list) return;
    if (!items || items.length === 0) {
        list.classList.add('text-muted');
        list.textContent = 'No active streams.';
        return;
    }
    list.classList.remove('text-muted');
    list.innerHTML = items.map(item => {
        const mac = escapeHtml(item.mac || '-');
        const total = formatDuration(item.total_duration || 0);
        const avg = formatDuration(item.avg_duration || 0);
        return `
            <div class="dashboard-simple-item">
                <strong>${mac}</strong>
                <span>${total} (avg ${avg})</span>
            </div>
        `;
    }).join('');
}

function renderTopFailedMacs(items) {
    const list = document.getElementById('topFailedMacsList');
    if (!list) return;
    if (!items || items.length === 0) {
        list.classList.add('text-muted');
        list.textContent = 'No failures in last 24h.';
        return;
    }
    list.classList.remove('text-muted');
    list.innerHTML = items.map(item => `
        <div class="dashboard-simple-item">
            <strong>${escapeHtml(item.label || '-')}</strong>
            <span>${item.count || 0}</span>
        </div>
    `).join('');
}

function renderTopReliableChannels(items) {
    const list = document.getElementById('topReliableChannelsList');
    if (!list) return;
    if (!items || items.length === 0) {
        list.classList.add('text-muted');
        list.textContent = 'Not enough stream history.';
        return;
    }
    list.classList.remove('text-muted');
    list.innerHTML = items.map(item => {
        const channel = escapeHtml(item.channel_name || '-');
        const portal = escapeHtml(item.portal_name || '-');
        const starts = Number(item.starts || 0);
        const successes = Number(item.successes || 0);
        const ratio = Math.round((Number(item.ratio || 0) * 100));
        return `
            <div class="dashboard-simple-item">
                <strong>${channel}</strong>
                <span>${ratio}% (${successes}/${starts}) · ${portal}</span>
            </div>
        `;
    }).join('');
}

function renderSpeedtest(mode, data) {
    const key = mode === 'direct' ? 'Direct' : 'Proxy';
    if (!data) {
        setText(`speedtest${key}Line1`, 'IP: -');
        setText(`speedtest${key}Line2`, 'Latency: -');
        setText(`speedtest${key}Line3`, 'Download: -');
        setText(`speedtest${key}Line4`, 'Updated: -');
        return;
    }

    const normalizedIpInfo = normalizeIpCountry(data.public_ip, data.country_flag, data.country_code);
    const ipPart = [normalizedIpInfo.flag, normalizedIpInfo.ip].filter(Boolean).join(' ').trim();
    const latency = data.latency_ms ?? data.ip_lookup_ms ?? '-';
    const download = data.download_mbps != null ? `${data.download_mbps} Mbps` : '-';
    const provider = (data.provider_used || data.provider_requested || 'http').toUpperCase();
    const updated = data.tested_at ? formatTimestamp((Number(data.tested_at) || 0) * 1000) : '-';
    const status = data.ok ? 'OK' : `FAILED${data.message ? ` (${data.message})` : ''}`;

    setText(`speedtest${key}Line1`, `IP: ${ipPart}`);
    setText(`speedtest${key}Line2`, `Latency: ${latency} ms · ${data.country_name || '-'}`);
    setText(`speedtest${key}Line3`, `Download: ${download} · ${provider} · ${status}`);
    setText(`speedtest${key}Line4`, `Updated: ${updated}`);
}

function normalizeIpCountry(publicIp, countryFlag, countryCode) {
    let ip = String(publicIp || '').trim();
    let flag = normalizeCountryFlag(countryFlag, countryCode);
    if (!flag && ip) {
        const prefixed = ip.match(/^([A-Za-z]{2})\s+(.+)$/);
        if (prefixed) {
            flag = countryCodeToEmoji(prefixed[1]);
            ip = prefixed[2].trim();
        }
    }
    return {
        flag: flag || '',
        ip: ip || '-'
    };
}

function normalizeCountryFlag(flag, countryCode) {
    const raw = String(flag || '').trim();
    if (raw) {
        if (raw.length === 2 && /^[A-Za-z]{2}$/.test(raw)) {
            return countryCodeToEmoji(raw);
        }
        return raw;
    }
    const code = String(countryCode || '').trim();
    if (code.length === 2 && /^[A-Za-z]{2}$/.test(code)) {
        return countryCodeToEmoji(code);
    }
    return '';
}

function countryCodeToEmoji(code) {
    const cc = String(code || '').toUpperCase();
    if (cc.length !== 2 || !/^[A-Z]{2}$/.test(cc)) return '';
    return String.fromCodePoint(cc.charCodeAt(0) + 127397) + String.fromCodePoint(cc.charCodeAt(1) + 127397);
}

function runDashboardSpeedtest(mode) {
    const btnId = mode === 'direct' ? 'btnRunDirectSpeedtest' : 'btnRunProxySpeedtest';
    const button = document.getElementById(btnId);
    if (button) button.disabled = true;
    setSpeedtestRunning(mode, true);
    fetch('/api/settings/speedtest/test', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mode })
    })
        .then(async response => {
            const payload = await response.json().catch(() => ({}));
            if (payload && typeof payload === 'object') {
                renderSpeedtest(mode, payload);
            }
            if (!response.ok || !payload.ok) {
                throw new Error(payload.message || 'Speedtest failed');
            }
            showNotification(`Speedtest (${mode}) completed`, 'success', 2000);
            return refreshDashboardStats();
        })
        .catch(error => {
            renderSpeedtest(mode, {
                ok: false,
                mode,
                message: error.message || String(error),
                tested_at: Math.floor(Date.now() / 1000)
            });
            showNotification(`Speedtest (${mode}) failed: ${error.message || error}`, 'error', 4000);
        })
        .finally(() => {
            setSpeedtestRunning(mode, false);
            if (button) button.disabled = false;
        });
}

function setSpeedtestRunning(mode, running) {
    if (!running) return;
    const key = mode === 'direct' ? 'Direct' : 'Proxy';
    setText(`speedtest${key}Line1`, 'IP: Testing...');
    setText(`speedtest${key}Line2`, 'Latency: Testing...');
    setText(`speedtest${key}Line3`, 'Download: Testing...');
    setText(`speedtest${key}Line4`, 'Updated: Running...');
}

function refreshLineup() {
    fetch('/refresh_lineup', { method: 'POST' })
        .then(response => response.json())
        .then(data => {
            showNotification('Lineup refreshed successfully!', 'success');
        })
        .catch(error => {
            console.error('Error refreshing lineup:', error);
            showNotification('Error refreshing lineup', 'error');
        });
}

function updatePlaylist() {
    fetch('/update_playlistm3u', { method: 'POST' })
        .then(response => response.text())
        .then(data => {
            showNotification('Playlist updated successfully!', 'success');
        })
        .catch(error => {
            console.error('Error updating playlist:', error);
            showNotification('Error updating playlist', 'error');
        });
}

function copyToClipboard(elementId) {
    const element = document.getElementById(elementId);
    const text = element.value;

    // Use modern Clipboard API
    navigator.clipboard.writeText(text).then(() => {
        // Visual feedback
        const button = element.nextElementSibling;
        const originalHtml = button.innerHTML;
        button.innerHTML = '<i class="fas fa-check"></i>';
        button.classList.add('btn-success');
        button.classList.remove('btn-outline-secondary');

        setTimeout(() => {
            button.innerHTML = originalHtml;
            button.classList.remove('btn-success');
            button.classList.add('btn-outline-secondary');
        }, 2000);

        showNotification('Copied to clipboard!', 'success', 1500);
    }).catch(err => {
        console.error('Failed to copy:', err);
        showNotification('Failed to copy to clipboard', 'error');
    });
}

// Initialize page
function initializeDashboard() {
    const baseUrl = window.location.origin;
    const serverUrlEl = document.getElementById('serverUrl');
    const xmltvUrlEl = document.getElementById('xmltvUrl');
    const playlistUrlEl = document.getElementById('playlistUrl');
    const lastUpdatedEl = document.getElementById('lastUpdated');

    if (serverUrlEl) serverUrlEl.textContent = baseUrl;
    if (xmltvUrlEl) xmltvUrlEl.value = `${baseUrl}/xmltv`;
    if (playlistUrlEl) playlistUrlEl.value = `${baseUrl}/playlist.m3u`;
    if (lastUpdatedEl) lastUpdatedEl.textContent = new Date().toLocaleString();
    const proxyBtn = document.getElementById('btnRunProxySpeedtest');
    const directBtn = document.getElementById('btnRunDirectSpeedtest');
    if (proxyBtn) proxyBtn.addEventListener('click', () => runDashboardSpeedtest('proxy'));
    if (directBtn) directBtn.addEventListener('click', () => runDashboardSpeedtest('direct'));

    // Initial load
    refreshStreams();
    refreshDashboardStats();

    // Auto-refresh streams every 30 seconds
    streamsRefreshInterval = setInterval(function() {
        refreshStreams();
        refreshDashboardStats();
    }, 30000);
}

initializeDashboard();

        window.refreshStreams = refreshStreams;
        window.copyToClipboard = copyToClipboard;
        window.refreshLineup = refreshLineup;
        window.updatePlaylist = updatePlaylist;

    }
    function cleanup() {
        if (streamsRefreshInterval) {
            clearInterval(streamsRefreshInterval);
            streamsRefreshInterval = null;
        }
    }
    window.App && window.App.register('dashboard', initDashboardPage, cleanup);
})();
