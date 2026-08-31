import React from 'react';
import { cn } from '@/lib/cn';

export type BadgeVariant =
  | 'default'
  | 'success'
  | 'warning'
  | 'error'
  | 'info'
  | 'neutral'
  | 'outline'
  | 'destructive'
  | 'priority-critical'
  | 'priority-high'
  | 'priority-medium'
  | 'priority-low';

export interface BadgeProps {
  children: React.ReactNode;
  variant?: BadgeVariant;
  size?: 'sm' | 'md';
  className?: string;
  icon?: React.ReactNode;
}

const variantStyles: Record<BadgeVariant, string> = {
  default: 'bg-gray-100 text-gray-800',
  success: 'bg-green-100 text-green-800',
  warning: 'bg-yellow-100 text-yellow-800',
  error: 'bg-red-100 text-red-800',
  info: 'bg-blue-100 text-blue-800',
  neutral: 'bg-gray-100 text-gray-600',
  outline: 'border border-gray-300 text-gray-700 bg-transparent',
  destructive: 'bg-red-600 text-white hover:bg-red-700',
  'priority-critical': 'bg-red-100 text-red-800',
  'priority-high': 'bg-orange-100 text-orange-800',
  'priority-medium': 'bg-yellow-100 text-yellow-800',
  'priority-low': 'bg-green-100 text-green-800',
};

/**
 * Badge component for status indicators, labels, and tags
 * Supports multiple variants for different semantic meanings
 */
export const Badge: React.FC<BadgeProps> = ({
  children,
  variant = 'default',
  size = 'md',
  className,
  icon,
}) => {
  const sizeStyles = {
    sm: 'px-2 py-0.5 text-xs',
    md: 'px-2.5 py-0.5 text-sm',
  };

  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 rounded-full font-medium',
        variantStyles[variant],
        sizeStyles[size],
        className
      )}
    >
      {icon && <span className="shrink-0">{icon}</span>}
      {children}
    </span>
  );
};

/**
 * Helper function to get badge variant from status strings
 */
export function getBadgeVariantFromStatus(
  status: string
): BadgeVariant {
  const normalizedStatus = status.toLowerCase();

  switch (normalizedStatus) {
    case 'online':
    case 'active':
    case 'running':
    case 'completed':
    case 'success':
      return 'success';
    case 'offline':
    case 'inactive':
    case 'stopped':
      return 'neutral';
    case 'maintenance':
    case 'pending':
    case 'in_progress':
    case 'in-review':
      return 'warning';
    case 'faulty':
    case 'error':
    case 'failed':
    case 'overdue':
    case 'cancelled':
      return 'error';
    case 'assigned':
    case 'draft':
      return 'info';
    default:
      return 'default';
  }
}

/**
 * Helper function to get badge variant from priority strings
 */
export function getBadgeVariantFromPriority(
  priority: string
): BadgeVariant {
  const normalizedPriority = priority.toLowerCase();

  switch (normalizedPriority) {
    case 'critical':
    case 'urgent':
      return 'priority-critical';
    case 'high':
      return 'priority-high';
    case 'medium':
      return 'priority-medium';
    case 'low':
      return 'priority-low';
    default:
      return 'default';
  }
}

/**
 * Helper function to get status color classes for text or background
 */
export function getStatusColor(
  status: string,
  type: 'text' | 'bg' = 'text'
): string {
  const normalizedStatus = status.toLowerCase();
  
  const statusColors: Record<string, { text: string; bg: string }> = {
    operational: { text: 'text-green-600', bg: 'bg-green-500' },
    warning: { text: 'text-yellow-600', bg: 'bg-yellow-500' },
    critical: { text: 'text-red-600', bg: 'bg-red-500' },
    offline: { text: 'text-gray-600', bg: 'bg-gray-500' },
    maintenance: { text: 'text-blue-600', bg: 'bg-blue-500' },
  };
  
  const colors = statusColors[normalizedStatus] || { text: 'text-gray-600', bg: 'bg-gray-500' };
  return colors[type];
}
